"""Email alerts and daily summaries for the people added on the dashboard's Email alerts page.

The list is saved to ALERTS_FILE (default data/alerts.json). A new address gets a 6-digit code first and
receives nothing else until that code is entered on the dashboard: that catches typos, and nobody is
signed up without asking.

Plant alerts. After every Plant Doctor analysis the bridge calls `on_result`. An email goes out when the
priority reaches high or critical (each person picks which), and then only when it matters:

- the first time it gets there
- when it gets worse (high -> critical)
- every REPEAT_AFTER while it stays there, as a reminder that it still needs doing

Once the priority drops below high, a new alert waits at least QUIET_GAP after the last one, so a reading
that flickers around the threshold doesn't send an email every few minutes. A device that stops reporting
for OFFLINE_AFTER gets one "offline" email per outage.

Daily summary. Once a day at DAILY_SUMMARY_HOUR (local time) everyone who wants it gets each device's
state, the last advice, the waterings and the reminders found in the inbox.

Alerts and summaries are sent from a background thread, so a slow mail server never holds up the
analysis. Codes and test emails are sent while the request waits, so the dashboard can show an error.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import queue
import re
import secrets
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import email_templates as templates
from .device_state import DeviceStore, iso
from .mailer import MailError, Mailer
from .schemas import CareResult, priority_code
from .watering import WateringDecision

log = logging.getLogger(__name__)

ALERT_FROM = priority_code("high")
REPEAT_AFTER = timedelta(hours=6)
QUIET_GAP = timedelta(hours=1)
OFFLINE_AFTER = timedelta(minutes=15)
CODE_TTL = timedelta(minutes=15)
CODE_RESEND_AFTER = timedelta(seconds=60)
TEST_EVERY = timedelta(seconds=60)
MAX_CODE_ATTEMPTS = 5
MAX_CODES_PER_HOUR = 10
MAX_RECIPIENTS = 10
RECENT = 25
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AlertsError(Exception):
    """A request the dashboard can't have; `status` is the HTTP status for it."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass
class Recipient:
    id: str
    email: str
    added_at: datetime
    verified: bool = False
    alerts: bool = True
    min_priority: str = "high"  # high | critical
    daily: bool = True
    # The pending sign-up code. Only its hash is kept, and it never leaves the server.
    code_hash: str | None = None
    code_expires: datetime | None = None
    code_sent_at: datetime | None = None
    attempts: int = 0

    def public(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "verified": self.verified,
            "alerts": self.alerts,
            "min_priority": self.min_priority,
            "daily": self.daily,
            "added_at": iso(self.added_at),
            "code_pending": self.code_hash is not None,
        }

    def to_json(self) -> dict:
        return {
            **{key: value for key, value in self.public().items() if key != "code_pending"},
            "code_hash": self.code_hash,
            "code_expires": iso(self.code_expires),
            "code_sent_at": iso(self.code_sent_at),
            "attempts": self.attempts,
        }

    @classmethod
    def from_json(cls, data: dict) -> Recipient:
        return cls(
            id=str(data["id"]),
            email=str(data["email"]),
            added_at=datetime.fromisoformat(data["added_at"]),
            verified=bool(data.get("verified")),
            alerts=bool(data.get("alerts", True)),
            min_priority="critical" if data.get("min_priority") == "critical" else "high",
            daily=bool(data.get("daily", True)),
            code_hash=data.get("code_hash"),
            code_expires=_parse_time(data.get("code_expires")),
            code_sent_at=_parse_time(data.get("code_sent_at")),
            attempts=int(data.get("attempts", 0)),
        )


@dataclass
class _Episode:
    """The last alert sent for one device."""

    level: int
    sent_at: datetime
    active: bool  # still at high or above since then


class AlertCenter:
    """Thread-safe: API requests change the list while the analysis worker and the scheduler read it."""

    def __init__(
        self,
        mailer: Mailer | None,
        store: DeviceStore,
        path: Path | str | None = None,
        timezone_name: str = "Asia/Colombo",
        daily_hour: int = 8,
        dashboard_url: str | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ):
        self.mailer = mailer
        self.store = store
        self.path = Path(path) if path else None
        self.tz = ZoneInfo(timezone_name)
        self.daily_hour = daily_hour
        self.dashboard_url = dashboard_url
        self.clock = clock
        self._lock = threading.Lock()
        self._recipients: list[Recipient] = []
        self._last_daily: str | None = None  # local date of the last summary
        self._episodes: dict[str, _Episode] = {}
        self._offline: set[str] = set()  # devices already reported offline
        self._code_sends: deque[datetime] = deque()
        self._tested: dict[str, datetime] = {}
        self._recent: deque[dict] = deque(maxlen=RECENT)
        self._outbox: queue.Queue[tuple[str, str, tuple[str, str, str]] | None] = queue.Queue(maxsize=200)
        self._stop = threading.Event()
        self._load()

    # ------------------------------------------------------------------ lifecycle (bridge)

    def start(self) -> None:
        """Send queued emails, and check every 30 s for the daily summary and offline devices."""
        threading.Thread(target=self._send_loop, name="email-outbox", daemon=True).start()
        threading.Thread(target=self._schedule_loop, name="email-scheduler", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self._outbox.put(None)

    def _send_loop(self) -> None:
        while (item := self._outbox.get()) is not None:
            self._deliver(*item)

    def _schedule_loop(self) -> None:
        while not self._stop.wait(30):
            try:
                self.tick()
            except Exception:
                log.exception("Email scheduler failed")

    def send_pending(self) -> None:
        """Send queued emails on the calling thread (for tests and scripts)."""
        while True:
            try:
                item = self._outbox.get_nowait()
            except queue.Empty:
                return
            if item is not None:
                self._deliver(*item)

    # ------------------------------------------------------------------ the dashboard page

    @property
    def configured(self) -> bool:
        return self.mailer is not None

    def overview(self) -> dict:
        with self._lock:
            recipients = [r.public() for r in self._recipients]
            recent = list(reversed(self._recent))
        return {
            "configured": self.configured,
            "sender": self.mailer.username if self.mailer else None,
            "smtp_host": self.mailer.host if self.mailer else None,
            "daily_hour": self.daily_hour,
            "timezone": self.tz.key,
            "rules": {
                "repeat_after_h": REPEAT_AFTER.total_seconds() / 3600,
                "offline_after_min": OFFLINE_AFTER.total_seconds() / 60,
            },
            "recipients": recipients,
            "recent": recent,
        }

    def add(self, email: str) -> dict:
        """Add an address and send it a sign-up code. If the code can't be sent, nothing is added."""
        self._require_mailer()
        email = email.strip()
        if len(email) > 254 or not EMAIL_PATTERN.match(email):
            raise AlertsError(422, "That doesn't look like an email address.")
        now = self.clock()
        with self._lock:
            if any(r.email.lower() == email.lower() for r in self._recipients):
                raise AlertsError(409, f"{email} is already on the list.")
            if len(self._recipients) >= MAX_RECIPIENTS:
                raise AlertsError(409, f"The list is full ({MAX_RECIPIENTS} addresses). Remove one first.")
            recipient = Recipient(id=secrets.token_hex(4), email=email, added_at=now)
            code = self._new_code(recipient, now)
            self._recipients.append(recipient)
            self._save()
        try:
            self._send_now("code", email, templates.code_email(code, int(CODE_TTL.total_seconds() // 60)))
        except AlertsError:
            with self._lock:
                self._recipients = [r for r in self._recipients if r.id != recipient.id]
                self._save()
            raise
        log.info("Email alerts: sign-up code sent to %s", email)
        return recipient.public()

    def resend_code(self, recipient_id: str) -> dict:
        self._require_mailer()
        now = self.clock()
        with self._lock:
            recipient = self._get(recipient_id)
            if recipient.verified:
                raise AlertsError(409, f"{recipient.email} is already confirmed.")
            if recipient.code_sent_at and now - recipient.code_sent_at < CODE_RESEND_AFTER:
                wait = (CODE_RESEND_AFTER - (now - recipient.code_sent_at)).total_seconds()
                raise AlertsError(429, f"Wait {wait:.0f} s before asking for another code.")
            code = self._new_code(recipient, now)
            self._save()
            email = recipient.email
        self._send_now("code", email, templates.code_email(code, int(CODE_TTL.total_seconds() // 60)))
        return recipient.public()

    def verify(self, recipient_id: str, code: str) -> dict:
        now = self.clock()
        with self._lock:
            recipient = self._get(recipient_id)
            if recipient.verified:
                return recipient.public()
            if recipient.code_hash is None or recipient.code_expires is None or now > recipient.code_expires:
                raise AlertsError(400, "That code has expired. Send a new one.")
            if not hmac.compare_digest(recipient.code_hash, _hash(recipient.id, code.strip())):
                recipient.attempts += 1
                if recipient.attempts >= MAX_CODE_ATTEMPTS:
                    recipient.code_hash = recipient.code_expires = None
                    self._save()
                    raise AlertsError(429, "Too many wrong codes. Send a new one.")
                self._save()
                raise AlertsError(400, "That code isn't right. Check the latest email from GreenPulse.")
            recipient.verified = True
            recipient.code_hash = recipient.code_expires = None
            recipient.attempts = 0
            self._save()
        log.info("Email alerts: %s confirmed", recipient.email)
        return recipient.public()

    def update(self, recipient_id: str, alerts: bool, min_priority: str, daily: bool) -> dict:
        if min_priority not in ("high", "critical"):
            raise AlertsError(422, "min_priority must be high or critical.")
        with self._lock:
            recipient = self._get(recipient_id)
            recipient.alerts, recipient.min_priority, recipient.daily = alerts, min_priority, daily
            self._save()
            return recipient.public()

    def remove(self, recipient_id: str) -> None:
        with self._lock:
            recipient = self._get(recipient_id)
            self._recipients.remove(recipient)
            self._save()
        log.info("Email alerts: %s removed", recipient.email)

    def send_test(self, recipient_id: str) -> None:
        self._require_mailer()
        now = self.clock()
        with self._lock:
            recipient = self._get(recipient_id)
            if not recipient.verified:
                raise AlertsError(409, "Confirm the address with its code first.")
            last = self._tested.get(recipient_id)
            if last and now - last < TEST_EVERY:
                raise AlertsError(429, "A test email was just sent. Wait a minute before sending another.")
            self._tested[recipient_id] = now
            gets = self._describe(recipient)
            email = recipient.email
        self._send_now("test", email, templates.sample_email(email, gets, self.dashboard_url))

    # ------------------------------------------------------------------ alerts (bridge, scheduler)

    def on_result(self, result: CareResult, decision: WateringDecision | None = None) -> None:
        """Called after every Plant Doctor analysis; queues an alert when one is due."""
        level = priority_code(result.priority)
        now = self.clock()
        with self._lock:
            episode = self._episodes.get(result.device_id)
            if level < ALERT_FROM:
                if episode:
                    episode.active = False
                return
            kind = _alert_kind(episode, level, now)
            if kind is None:
                return
            self._episodes[result.device_id] = _Episode(level, now, active=True)
            to = [r.email for r in self._recipients if r.verified and r.alerts and level >= priority_code(r.min_priority)]
        for email in to:
            self._queue("alert", email, templates.alert_email(result, decision, kind, email, self.tz, self.dashboard_url))
        if to:
            log.info("%s  alert email (%s, %s) to %d address(es)", result.device_id, result.priority, kind, len(to))

    def tick(self) -> None:
        now = self.clock()
        self._check_offline(now)
        self._check_daily(now)

    def _check_offline(self, now: datetime) -> None:
        for device in self.store.devices():
            device_id, last_seen = device["device_id"], datetime.fromisoformat(device["last_seen"])
            with self._lock:
                if now - last_seen < OFFLINE_AFTER:
                    self._offline.discard(device_id)
                    continue
                if device_id in self._offline:
                    continue
                self._offline.add(device_id)
                to = [r.email for r in self._recipients if r.verified and r.alerts]
            plant = self.store.profile_for(device_id).name
            for email in to:
                self._queue("offline", email, templates.offline_email(device_id, plant, last_seen, email, self.tz, self.dashboard_url))
            log.warning("%s  offline since %s; told %d address(es)", device_id, iso(last_seen), len(to))

    def _check_daily(self, now: datetime) -> None:
        local = now.astimezone(self.tz)
        today = local.date().isoformat()
        with self._lock:
            if local.hour != self.daily_hour or self._last_daily == today:
                return
            self._last_daily = today
            self._save()
            to = [r.email for r in self._recipients if r.verified and r.daily]
        if not to:
            return
        devices = []
        for device in self.store.devices():
            snapshot = self.store.snapshot(device["device_id"])
            runs = [e for e in self.store.pump_events(device["device_id"], 24) if e.state == "on"]
            devices.append({**snapshot, "waterings": [{"source": e.source} for e in runs]})
        for email in to:
            self._queue("daily", email, templates.daily_email(devices, local, email, self.dashboard_url))
        log.info("Daily summary queued for %d address(es)", len(to))

    # ------------------------------------------------------------------ sending

    def _queue(self, kind: str, to: str, email: tuple[str, str, str]) -> None:
        if not self.mailer:
            return
        try:
            self._outbox.put_nowait((kind, to, email))
        except queue.Full:
            log.warning("Email outbox is full; dropping a %s email to %s", kind, to)

    def _deliver(self, kind: str, to: str, email: tuple[str, str, str]) -> None:
        try:
            self._send(kind, to, email)
        except MailError as exc:
            log.warning("Couldn't send the %s email to %s: %s", kind, to, exc)

    def _send_now(self, kind: str, to: str, email: tuple[str, str, str]) -> None:
        try:
            self._send(kind, to, email)
        except MailError as exc:
            raise AlertsError(502, str(exc)) from None

    def _send(self, kind: str, to: str, email: tuple[str, str, str]) -> None:
        assert self.mailer is not None
        subject, text, html = email
        entry = {"at": iso(self.clock()), "to": to, "kind": kind, "subject": subject, "ok": True, "error": None}
        try:
            self.mailer.send(to, subject, text, html, kind=kind)
        except MailError as exc:
            entry.update(ok=False, error=str(exc))
            raise
        finally:
            with self._lock:
                self._recent.append(entry)

    # ------------------------------------------------------------------ helpers

    def _require_mailer(self) -> None:
        if not self.mailer:
            raise AlertsError(503, "Sending email isn't set up on the server. Set SMTP_HOST in backend/.env and restart.")

    def _get(self, recipient_id: str) -> Recipient:
        """Call with the lock held."""
        for recipient in self._recipients:
            if recipient.id == recipient_id:
                return recipient
        raise AlertsError(404, "That address is no longer on the list.")

    def _new_code(self, recipient: Recipient, now: datetime) -> str:
        """Call with the lock held. Also limits how many codes go out per hour, whoever asks."""
        while self._code_sends and now - self._code_sends[0] >= timedelta(hours=1):
            self._code_sends.popleft()
        if len(self._code_sends) >= MAX_CODES_PER_HOUR:
            raise AlertsError(429, "Too many codes were sent in the last hour. Try again later.")
        self._code_sends.append(now)
        code = f"{secrets.randbelow(1_000_000):06d}"
        recipient.code_hash = _hash(recipient.id, code)
        recipient.code_expires = now + CODE_TTL
        recipient.code_sent_at = now
        recipient.attempts = 0
        return code

    def _describe(self, recipient: Recipient) -> list[str]:
        gets = []
        if recipient.alerts:
            level = "critical" if recipient.min_priority == "critical" else "high and critical"
            gets.append(f"plant alerts at {level} priority, and when a device goes offline")
        if recipient.daily:
            gets.append(f"a daily summary at {self.daily_hour:02d}:00 ({self.tz.key})")
        return gets

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._recipients = [Recipient.from_json(item) for item in data.get("recipients", [])]
            self._last_daily = data.get("last_daily")
        except (ValueError, KeyError, TypeError) as exc:
            log.error("Can't read %s (%s); starting with an empty email list", self.path, exc)

    def _save(self) -> None:
        """Write the whole file atomically. Call with the lock held."""
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"recipients": [r.to_json() for r in self._recipients], "last_daily": self._last_daily}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)


def _alert_kind(episode: _Episode | None, level: int, now: datetime) -> str | None:
    """Whether a reading at `level` (high or above) deserves an email: "new", "worse", "still" or None."""
    if episode is None:
        return "new"
    if level > episode.level:
        return "worse"
    if episode.active:
        return "still" if now - episode.sent_at >= REPEAT_AFTER else None
    return "new" if now - episode.sent_at >= QUIET_GAP else None


def _hash(recipient_id: str, code: str) -> str:
    return hashlib.sha256(f"{recipient_id}:{code}".encode()).hexdigest()


def _parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
