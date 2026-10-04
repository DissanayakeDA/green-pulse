"""Notification Agent: finds plant-care reminders and travel plans in the user's email.

ImapNotificationAgent reads recent messages from a real mailbox over IMAP (Gmail: an app password).
DummyNotificationAgent reads a hardcoded inbox (see dummy_data) for the offline demo and the tests.
Both produce the same NotificationReport, and any class with a `run() -> NotificationReport` method
can be passed to orchestrator.build_service().

Only messages that match a plant-care or travel keyword are reported, so the rest of the inbox never
reaches the LLM. The Plant Doctor prompt treats the matching messages as untrusted data.
"""

from __future__ import annotations

import email
import email.policy
import html
import imaplib
import logging
import re
import time
from collections.abc import Callable
from datetime import date, timedelta, timezone
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from typing import Protocol

from ..schemas import NotificationReport, Reminder

log = logging.getLogger(__name__)

# First matching kind wins, so the more specific kinds come before "watering". Whole words only:
# "waterproof headphones" is not a watering reminder.
KEYWORDS: dict[str, re.Pattern[str]] = {
    "travel": re.compile(r"\b(trips?|travel(?:ling|ing)?|vacation|holidays?|flights?|booking confirmed)\b"),
    "fertilising": re.compile(r"\b(fertili[sz]\w*|plant food)\b"),
    "repotting": re.compile(r"\brepot\w*"),
    "watering": re.compile(r"\bwater(?:s|ed|ing)?\b"),
}
MAX_REMINDERS = 5
MAX_DETAIL_CHARS = 300


class NotificationAgent(Protocol):
    name: str

    def run(self) -> NotificationReport: ...


def find_reminders(messages: list[dict], source: str) -> NotificationReport:
    """messages: dicts with from, subject, body and optionally received, newest first."""
    reminders = []
    for message in messages:
        text = f"{message['subject']} {message['body']}".lower()
        kind = next((k for k, pattern in KEYWORDS.items() if pattern.search(text)), None)
        if kind:
            detail = " ".join(message["body"].split())
            reminders.append(
                Reminder(
                    kind=kind,
                    title=message["subject"],
                    detail=detail[:MAX_DETAIL_CHARS],
                    sender=message["from"],
                    received=message.get("received"),
                )
            )
    reminders = reminders[:MAX_REMINDERS]

    if reminders:
        summary = "Relevant messages: " + "; ".join(f"{r.title} ({r.kind})" for r in reminders) + "."
    else:
        summary = f"No plant-care reminders or travel plans among {len(messages)} recent messages."
    return NotificationReport(source=source, summary=summary, reminders=reminders)


class DummyNotificationAgent:
    """Filters a hardcoded list of messages (see dummy_data) for plant-care reminders and plans."""

    name = "notification"

    def __init__(self, messages: list[dict]):
        self.messages = messages

    def run(self) -> NotificationReport:
        return find_reminders(self.messages, "dummy")


class NoMailboxAgent:
    """Used by the live bridge when no mailbox is configured: says so instead of inventing an inbox."""

    name = "notification"

    def run(self) -> NotificationReport:
        return NotificationReport(source="not-configured", summary="Email is not connected, so no reminders were checked.")


def _imap_date(day: date) -> str:
    # IMAP wants English month names whatever the system locale is.
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{day.day:02d}-{months[day.month - 1]}-{day.year}"


def _html_to_text(markup: str) -> str:
    markup = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", markup)
    return html.unescape(re.sub(r"<[^>]+>", " ", markup))


def parse_email(raw: bytes) -> dict:
    """One RFC 822 message -> {from, subject, body, received}. The body is the plain-text part, or the
    HTML part stripped of tags."""
    message: EmailMessage = email.message_from_bytes(raw, policy=email.policy.default)
    body = ""
    part = message.get_body(preferencelist=("plain", "html"))
    if part is not None:
        try:
            body = part.get_content()
        except (LookupError, ValueError):  # unknown charset or broken encoding
            body = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
        if part.get_content_type() == "text/html":
            body = _html_to_text(body)

    received = None
    if message["date"]:
        try:
            received = parsedate_to_datetime(str(message["date"]))
            if received.tzinfo is None:
                received = received.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass
    return {
        "from": str(message["from"] or ""),
        "subject": str(message["subject"] or "(no subject)"),
        "body": body,
        "received": received,
    }


class ImapNotificationAgent:
    """Reads the newest messages of the last `lookback_days` from a mailbox over IMAP (SSL).

    The mailbox is opened read-only and messages are fetched with BODY.PEEK, so nothing is marked as
    read. Only the first 64 KB of each message is downloaded, which skips large attachments. The
    result is reused for `cache_s`; if a later fetch fails, the last result is used for up to
    `max_stale_s`, after which the orchestrator reports notifications as unavailable.
    """

    name = "notification"
    FETCH_BYTES = 65536

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        folder: str = "INBOX",
        lookback_days: int = 7,
        max_messages: int = 30,
        cache_s: float = 600,
        max_stale_s: float = 3 * 3600,
        timeout_s: float = 20,
        connect: Callable[..., imaplib.IMAP4] = imaplib.IMAP4_SSL,
        clock: Callable[[], float] = time.monotonic,
        today: Callable[[], date] = date.today,
    ):
        self.host = host
        self.username = username
        self._password = password
        self.folder = folder
        self.lookback_days = lookback_days
        self.max_messages = max_messages
        self.cache_s = cache_s
        self.max_stale_s = max_stale_s
        self.timeout_s = timeout_s
        self._connect = connect
        self._clock = clock
        self._today = today
        self._last: tuple[float, NotificationReport] | None = None

    def run(self) -> NotificationReport:
        now = self._clock()
        if self._last and now - self._last[0] < self.cache_s:
            return self._last[1]
        try:
            messages = self.fetch_messages()
        except Exception:
            if self._last and now - self._last[0] < self.max_stale_s:
                log.warning("Mailbox check failed; reusing the result from %.0f min ago", (now - self._last[0]) / 60)
                return self._last[1]
            raise
        report = find_reminders(messages, "email")
        self._last = (now, report)
        return report

    def fetch_messages(self) -> list[dict]:
        """The newest `max_messages` messages of the last `lookback_days`, newest first."""
        since = _imap_date(self._today() - timedelta(days=self.lookback_days))
        imap = self._connect(self.host, timeout=self.timeout_s)
        try:
            imap.login(self.username, self._password)
            status, _ = imap.select(f'"{self.folder}"', readonly=True)
            if status != "OK":
                raise RuntimeError(f"Mailbox folder {self.folder!r} not found")
            _, data = imap.search(None, "SINCE", since)
            ids = data[0].split()[-self.max_messages :]
            if not ids:
                return []
            _, parts = imap.fetch(b",".join(ids).decode(), f"(BODY.PEEK[]<0.{self.FETCH_BYTES}>)")
        finally:
            try:
                imap.logout()
            except Exception:
                pass

        messages = []
        for part in parts:
            if not isinstance(part, tuple):
                continue  # the b")" that closes each FETCH response
            try:
                messages.append(parse_email(part[1]))
            except Exception:
                log.warning("Skipping an email that could not be parsed", exc_info=True)
        messages.reverse()  # IMAP returns oldest first
        return messages
