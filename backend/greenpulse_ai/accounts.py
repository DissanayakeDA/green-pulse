"""Dashboard accounts: register with the registration code, sign in, and stay signed in with a cookie.

Anyone who knows REGISTRATION_CODE (backend/.env) can create an account on the dashboard's Register page.
With no code set, registration is closed and only the existing accounts can sign in. Every account can do
everything on the dashboard; there are no roles.

Accounts and sessions are saved to USERS_FILE (default data/users.json). Passwords are stored as scrypt
hashes and session tokens as SHA-256 hashes, so a copy of the file can't be used to sign in. A session
lasts SESSION_DAYS, or until its owner signs out.

After MAX_FAILURES wrong passwords in a row an account is locked for LOCKOUT, which slows down password
guessing. On the server, Nginx also limits how often one IP address can call /api/auth/.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .alerts import EMAIL_PATTERN
from .device_state import iso

log = logging.getLogger(__name__)

SESSION_COOKIE = "gp_session"
SESSION_DAYS = 30
MIN_PASSWORD = 8
MAX_FAILURES = 5
LOCKOUT = timedelta(minutes=5)
MAX_ACCOUNTS = 50
# scrypt cost: about 50 ms and 16 MB per hash, fine for a few sign-ins a day on a t3.micro.
SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AccountsError(Exception):
    """A request the user can fix; `status` is the HTTP status the API answers with."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass
class Account:
    id: str
    name: str
    email: str
    password_hash: str
    created_at: datetime

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "email": self.email, "created_at": iso(self.created_at)}

    def to_json(self) -> dict:
        return {**self.public(), "password_hash": self.password_hash}

    @classmethod
    def from_json(cls, data: dict) -> Account:
        return cls(
            id=data["id"],
            name=data["name"],
            email=data["email"],
            password_hash=data["password_hash"],
            created_at=datetime.fromisoformat(data["created_at"]),
        )


class Accounts:
    """Thread-safe: the API runs requests in worker threads."""

    def __init__(
        self,
        path: Path | str | None = None,
        registration_code: str | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ):
        self.path = Path(path) if path else None
        self._code = registration_code.strip() if registration_code else None
        self.clock = clock
        self._lock = threading.Lock()
        self._accounts: list[Account] = []
        self._sessions: dict[str, tuple[str, datetime]] = {}  # token hash -> (account id, expires)
        self._failures: dict[str, tuple[int, datetime | None]] = {}  # email -> (wrong in a row, locked until)
        self._load()

    @property
    def registration_open(self) -> bool:
        return self._code is not None

    def count(self) -> int:
        with self._lock:
            return len(self._accounts)

    def register(self, name: str, email: str, password: str, code: str) -> tuple[Account, str]:
        """Create an account and sign it in. Returns the account and its session token."""
        name, email = name.strip(), email.strip().lower()
        if self._code is None:
            raise AccountsError(403, "Registration is closed: no registration code is set on the server.")
        if not hmac.compare_digest(code.strip().encode(), self._code.encode()):
            raise AccountsError(403, "That registration code isn't right. Ask the GreenPulse owner for it.")
        if not name:
            raise AccountsError(400, "Enter your name.")
        if not EMAIL_PATTERN.match(email):
            raise AccountsError(400, "That doesn't look like an email address.")
        if len(password) < MIN_PASSWORD:
            raise AccountsError(400, f"Use at least {MIN_PASSWORD} characters for the password.")
        password_hash = _hash_password(password)  # slow on purpose: outside the lock
        with self._lock:
            if any(a.email == email for a in self._accounts):
                raise AccountsError(409, "There's already an account for that email. Sign in instead.")
            if len(self._accounts) >= MAX_ACCOUNTS:
                raise AccountsError(409, f"This GreenPulse already has {MAX_ACCOUNTS} accounts, the most it allows.")
            account = Account(secrets.token_hex(4), name, email, password_hash, self.clock())
            self._accounts.append(account)
            token = self._new_session(account)
            self._save()
        log.info("New dashboard account: %s", email)
        return account, token

    def sign_in(self, email: str, password: str) -> tuple[Account, str]:
        """Check the password and start a session. Returns the account and its session token."""
        email = email.strip().lower()
        now = self.clock()
        with self._lock:
            wrong, locked_until = self._failures.get(email, (0, None))
            if locked_until and now < locked_until:
                minutes = max(1, round((locked_until - now).total_seconds() / 60))
                raise AccountsError(429, f"Too many wrong passwords. Try again in {minutes} min.")
            account = next((a for a in self._accounts if a.email == email), None)
        # An unknown email costs the same time as a wrong password, so the answer doesn't tell which it was.
        if not _check_password(password, account.password_hash if account else _DUMMY_HASH) or account is None:
            with self._lock:
                wrong += 1
                self._failures[email] = (0, now + LOCKOUT) if wrong >= MAX_FAILURES else (wrong, None)
            raise AccountsError(401, "Wrong email or password.")
        with self._lock:
            self._failures.pop(email, None)
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
            return next((a for a in self._accounts if a.id == session[0]), None)

    # ------------------------------------------------------------------ internals

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


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


_DUMMY_HASH = _hash_password(secrets.token_hex(16))
