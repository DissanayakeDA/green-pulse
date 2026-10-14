"""Dashboard accounts: register, confirm the email address with a 6-digit code, sign in, stay signed in.

Anyone can register on the dashboard's Register page with a name, an email address and a password. The
account only works once its owner enters the 6-digit code emailed to that address, so every account
belongs to a real mailbox. Registering needs email sending (SMTP_HOST); without it, registration is
closed and only existing accounts can sign in. Every account can do everything on the dashboard; there
are no roles.

Accounts and sessions are saved to USERS_FILE (default data/users.json). Passwords are stored as scrypt
hashes, and codes and session tokens as SHA-256 hashes, so a copy of the file can't be used to sign in.
A session lasts SESSION_DAYS, or until its owner signs out. An address that is never confirmed is
forgotten after UNCONFIRMED_KEEP, and until then registering it again just sends a new code.

Limits, against guessing and against the server being used to email strangers:
- a code expires after CODE_TTL and stops working after MAX_CODE_ATTEMPTS wrong tries
- a new code at most every CODE_RESEND_AFTER per address, and MAX_CODES_PER_HOUR in all
- MAX_FAILURES wrong passwords in a row lock an account for LOCKOUT
On the server, Nginx also limits how often one IP address can call /api/auth/.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import email_templates as templates
from .alerts import EMAIL_PATTERN
from .device_state import iso
from .mailer import MailError, Mailer

log = logging.getLogger(__name__)

SESSION_COOKIE = "gp_session"
SESSION_DAYS = 30
MIN_PASSWORD = 8
MAX_FAILURES = 5
LOCKOUT = timedelta(minutes=5)
MAX_ACCOUNTS = 50  # confirmed ones
CODE_TTL = timedelta(minutes=15)
CODE_RESEND_AFTER = timedelta(seconds=60)
MAX_CODE_ATTEMPTS = 5
MAX_CODES_PER_HOUR = 20
UNCONFIRMED_KEEP = timedelta(days=1)
# scrypt cost: about 50 ms and 16 MB per hash, fine for a few sign-ins a day on a t3.micro.
SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AccountsError(Exception):
    """A request the user can fix; `status` is the HTTP status the API answers with, and `reason` a word the
    dashboard can act on ("unconfirmed": show the code form)."""

    def __init__(self, status: int, message: str, reason: str | None = None):
        super().__init__(message)
        self.status = status
        self.reason = reason


@dataclass
class Account:
    id: str
    name: str
    email: str
    password_hash: str
    created_at: datetime
    confirmed: bool = False
    code_hash: str | None = None
    code_expires: datetime | None = None
    code_sent_at: datetime | None = None
    code_attempts: int = 0

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "email": self.email, "created_at": iso(self.created_at)}

    def to_json(self) -> dict:
        return {
            **self.public(),
            "password_hash": self.password_hash,
            "confirmed": self.confirmed,
            "code_hash": self.code_hash,
            "code_expires": iso(self.code_expires),
            "code_sent_at": iso(self.code_sent_at),
            "code_attempts": self.code_attempts,
        }

    @classmethod
    def from_json(cls, data: dict) -> Account:
        return cls(
            id=data["id"],
            name=data["name"],
            email=data["email"],
            password_hash=data["password_hash"],
            created_at=datetime.fromisoformat(data["created_at"]),
            confirmed=data.get("confirmed", True),  # accounts from before email confirmation
            code_hash=data.get("code_hash"),
            code_expires=_parse_time(data.get("code_expires")),
            code_sent_at=_parse_time(data.get("code_sent_at")),
            code_attempts=data.get("code_attempts", 0),
        )


class Accounts:
    """Thread-safe: the API runs requests in worker threads."""

    def __init__(self, path: Path | str | None = None, mailer: Mailer | None = None, clock: Callable[[], datetime] = _utcnow):
        self.path = Path(path) if path else None
        self.mailer = mailer
        self.clock = clock
        self._lock = threading.Lock()
        self._accounts: list[Account] = []
        self._sessions: dict[str, tuple[str, datetime]] = {}  # token hash -> (account id, expires)
        self._failures: dict[str, tuple[int, datetime | None]] = {}  # email -> (wrong in a row, locked until)
        self._code_sends: deque[datetime] = deque()
        self._load()

    @property
    def registration_open(self) -> bool:
        return self.mailer is not None

    def count(self) -> int:
        """Confirmed accounts."""
        with self._lock:
            return sum(1 for a in self._accounts if a.confirmed)

    def register(self, name: str, email: str, password: str) -> Account:
        """Create an unconfirmed account and email it a code. Registering an address that isn't confirmed yet
        again replaces its name and password and sends a new code."""
        if self.mailer is None:
            raise AccountsError(503, "Registration is closed: sending email isn't set up on the server (SMTP_HOST).")
        name, email = name.strip(), email.strip().lower()
        if not name:
            raise AccountsError(400, "Enter your name.")
        if not EMAIL_PATTERN.match(email):
            raise AccountsError(400, "That doesn't look like an email address.")
        if len(password) < MIN_PASSWORD:
            raise AccountsError(400, f"Use at least {MIN_PASSWORD} characters for the password.")
        password_hash = _hash_password(password)  # slow on purpose: outside the lock
        now = self.clock()
        with self._lock:
            self._forget_unconfirmed(now)
            account = self._find(email)
            new = account is None
            if account is None:
                if sum(1 for a in self._accounts if a.confirmed) >= MAX_ACCOUNTS:
                    raise AccountsError(409, f"This GreenPulse already has {MAX_ACCOUNTS} accounts, the most it allows.")
                account = Account(secrets.token_hex(4), name, email, password_hash, now)
            elif account.confirmed:
                raise AccountsError(409, "There's already an account for that email. Sign in instead.")
            else:
                self._check_resend(account, now)
                account.name, account.password_hash = name, password_hash
            code = self._new_code(account, now)
            if new:
                self._accounts.append(account)
            self._save()
        try:
            self._send_code(account, code)
        except AccountsError:
            if new:  # nothing was sent, so nothing to keep
                with self._lock:
                    self._accounts = [a for a in self._accounts if a.id != account.id]
                    self._save()
            raise
        log.info("Dashboard account registered, waiting for its code: %s", email)
        return account

    def confirm(self, email: str, code: str) -> tuple[Account, str]:
        """Check the emailed code, confirm the account and sign it in. Returns the account and its session token."""
        email = email.strip().lower()
        now = self.clock()
        with self._lock:
            account = self._find(email)
            if account is None:
                raise AccountsError(404, "There's no account waiting for that email. Register first.")
            if account.confirmed:
                raise AccountsError(409, "That email is already confirmed. Sign in instead.")
            if account.code_hash is None or account.code_expires is None or now > account.code_expires:
                raise AccountsError(400, "That code has expired. Send a new one.")
            if not hmac.compare_digest(account.code_hash, _code_hash(account.id, code.strip())):
                account.code_attempts += 1
                if account.code_attempts >= MAX_CODE_ATTEMPTS:
                    account.code_hash = account.code_expires = None
                    self._save()
                    raise AccountsError(429, "Too many wrong codes. Send a new one.")
                self._save()
                raise AccountsError(400, "That code isn't right. Check the latest email from GreenPulse.")
            account.confirmed = True
            account.code_hash = account.code_expires = None
            account.code_attempts = 0
            token = self._new_session(account)
            self._save()
        log.info("Dashboard account confirmed: %s", email)
        return account, token

    def resend_code(self, email: str) -> None:
        """Email a new code to an account that isn't confirmed yet. Quietly does nothing for any other address,
        so the answer doesn't tell who has an account."""
        if self.mailer is None:
            raise AccountsError(503, "Sending email isn't set up on the server (SMTP_HOST).")
        email = email.strip().lower()
        now = self.clock()
        with self._lock:
            account = self._find(email)
            if account is None or account.confirmed:
                return
            self._check_resend(account, now)
            code = self._new_code(account, now)
            self._save()
        self._send_code(account, code)

    def sign_in(self, email: str, password: str) -> tuple[Account, str]:
        """Check the password and start a session. Returns the account and its session token."""
        email = email.strip().lower()
        now = self.clock()
        with self._lock:
            wrong, locked_until = self._failures.get(email, (0, None))
            if locked_until and now < locked_until:
                minutes = max(1, round((locked_until - now).total_seconds() / 60))
                raise AccountsError(429, f"Too many wrong passwords. Try again in {minutes} min.")
            account = self._find(email)
        # An unknown email costs the same time as a wrong password, so the answer doesn't tell which it was.
        if not _check_password(password, account.password_hash if account else _DUMMY_HASH) or account is None:
            with self._lock:
                wrong += 1
                self._failures[email] = (0, now + LOCKOUT) if wrong >= MAX_FAILURES else (wrong, None)
            raise AccountsError(401, "Wrong email or password.")
        with self._lock:
            self._failures.pop(email, None)
            if not account.confirmed:
                raise AccountsError(
                    403, f"Confirm your email address first: enter the code we sent to {email}.", reason="unconfirmed"
                )
            token = self._new_session(account)
            self._save()
        return account, token

    def sign_out(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            if self._sessions.pop(_token_hash(token), None):
                self._save()

    def account_for(self, token: str | None) -> Account | None:
        """The account a session cookie belongs to, or None if it's missing, unknown or expired."""
        if not token:
            return None
        with self._lock:
            session = self._sessions.get(_token_hash(token))
            if session is None or session[1] <= self.clock():
                return None
            return next((a for a in self._accounts if a.id == session[0] and a.confirmed), None)

    # ------------------------------------------------------------------ internals

    def _find(self, email: str) -> Account | None:
        """Call with the lock held."""
        return next((a for a in self._accounts if a.email == email), None)

    def _forget_unconfirmed(self, now: datetime) -> None:
        """Call with the lock held."""
        self._accounts = [
            a for a in self._accounts if a.confirmed or now - (a.code_sent_at or a.created_at) < UNCONFIRMED_KEEP
        ]

    def _check_resend(self, account: Account, now: datetime) -> None:
        """Call with the lock held."""
        if account.code_sent_at and now - account.code_sent_at < CODE_RESEND_AFTER:
            wait = (CODE_RESEND_AFTER - (now - account.code_sent_at)).total_seconds()
            raise AccountsError(429, f"Wait {wait:.0f} s before asking for another code.")

    def _new_code(self, account: Account, now: datetime) -> str:
        """Call with the lock held. Also limits how many codes go out per hour, whoever asks."""
        while self._code_sends and now - self._code_sends[0] >= timedelta(hours=1):
            self._code_sends.popleft()
        if len(self._code_sends) >= MAX_CODES_PER_HOUR:
            raise AccountsError(429, "Too many sign-up emails were sent in the last hour. Try again later.")
        self._code_sends.append(now)
        code = f"{secrets.randbelow(1_000_000):06d}"
        account.code_hash = _code_hash(account.id, code)
        account.code_expires = now + CODE_TTL
        account.code_sent_at = now
        account.code_attempts = 0
        return code

    def _send_code(self, account: Account, code: str) -> None:
        assert self.mailer is not None
        subject, text, html = templates.account_code_email(account.name, code, int(CODE_TTL.total_seconds() // 60))
        try:
            self.mailer.send(account.email, subject, text, html, kind="account")
        except MailError as exc:
            raise AccountsError(502, f"Couldn't send the email: {exc}") from None

    def _new_session(self, account: Account) -> str:
        """Call with the lock held. Also drops expired sessions."""
        now = self.clock()
        self._sessions = {h: s for h, s in self._sessions.items() if s[1] > now}
        token = secrets.token_urlsafe(32)
        self._sessions[_token_hash(token)] = (account.id, now + timedelta(days=SESSION_DAYS))
        return token

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._accounts = [Account.from_json(item) for item in data.get("accounts", [])]
            self._sessions = {
                s["token_hash"]: (s["account"], datetime.fromisoformat(s["expires"])) for s in data.get("sessions", [])
            }
        except (ValueError, KeyError, TypeError) as exc:
            log.error("Can't read %s (%s); starting with no dashboard accounts", self.path, exc)

    def _save(self) -> None:
        """Write the whole file atomically, readable only by this user. Call with the lock held."""
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "accounts": [a.to_json() for a in self._accounts],
            "sessions": [{"token_hash": h, "account": a, "expires": iso(e)} for h, (a, e) in self._sessions.items()],
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def _check_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **SCRYPT)
    except ValueError:
        return False
    return hmac.compare_digest(candidate.hex(), digest)


def _code_hash(account_id: str, code: str) -> str:
    return hashlib.sha256(f"{account_id}:{code}".encode()).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


_DUMMY_HASH = _hash_password(secrets.token_hex(16))
