from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from greenpulse_ai.accounts import (
    CODE_RESEND_AFTER,
    CODE_TTL,
    LOCKOUT,
    MAX_CODE_ATTEMPTS,
    MAX_CODES_PER_HOUR,
    MAX_FAILURES,
    SESSION_COOKIE,
    SESSION_DAYS,
    UNCONFIRMED_KEEP,
    Accounts,
    AccountsError,
)
from greenpulse_ai.agents.chat import ChatAgent
from greenpulse_ai.api import create_app
from greenpulse_ai.device_state import DeviceStore
from greenpulse_ai.mailer import Mailer
from greenpulse_ai.plant_profiles import get_profile

from conftest import T0, FakeSmtp


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


def make_accounts(tmp_path, smtp=None, clock=None, mail=True):
    smtp = smtp or FakeSmtp()
    mailer = Mailer("smtppro.zoho.com", 465, "hello@kyndexlab.com", "app-password", connect=smtp) if mail else None
    return Accounts(tmp_path / "users.json", mailer, clock or Clock()), smtp


def last_code(smtp):
    return smtp.sent[-1]["Subject"][:6]


def status(call, *args):
    with pytest.raises(AccountsError) as error:
        call(*args)
    return error.value.status


def test_register_confirm_sign_in_and_out(tmp_path):
    accounts, smtp = make_accounts(tmp_path)
    account = accounts.register(" Dumindu ", "Dumindu@Example.com", "correct horse")
    assert (account.name, account.email, account.confirmed) == ("Dumindu", "dumindu@example.com", False)

    email = smtp.sent[-1]
    assert email["To"] == "dumindu@example.com" and email["X-GreenPulse"] == "account"
    assert "Hi Dumindu" in email.get_body(("plain",)).get_content()

    # Not usable until the code from the email is entered.
    with pytest.raises(AccountsError) as error:
        accounts.sign_in("dumindu@example.com", "correct horse")
    assert (error.value.status, error.value.reason) == (403, "unconfirmed")

    confirmed, token = accounts.confirm("DUMINDU@example.com", f" {last_code(smtp)} ")
    assert confirmed.confirmed and accounts.account_for(token) == confirmed

    _, second = accounts.sign_in("dumindu@example.com ", "correct horse")
    accounts.sign_out(token)
    assert accounts.account_for(token) is None
    assert accounts.account_for(second) == confirmed

    # Accounts and open sessions survive a restart.
    reloaded, _ = make_accounts(tmp_path)
    assert reloaded.count() == 1
    assert reloaded.account_for(second).email == "dumindu@example.com"


def test_registration_rules(tmp_path):
    closed, _ = make_accounts(tmp_path, mail=False)
    assert not closed.registration_open
    assert status(closed.register, "Ann", "ann@example.com", "long enough") == 503

    accounts, smtp = make_accounts(tmp_path)
    assert status(accounts.register, "Ann", "ann@example.com", "short") == 400
    assert status(accounts.register, "Ann", "not-an-email", "long enough") == 400
    assert status(accounts.register, "  ", "ann@example.com", "long enough") == 400
    assert smtp.sent == []

    accounts.register("Ann", "ann@example.com", "long enough")
    accounts.confirm("ann@example.com", last_code(smtp))
    assert status(accounts.register, "Ann", "ANN@example.com", "long enough") == 409


def test_codes_expire_and_allow_few_tries(tmp_path):
    clock = Clock()
    accounts, smtp = make_accounts(tmp_path, clock=clock)
    accounts.register("Ann", "ann@example.com", "long enough")
    code = last_code(smtp)
    wrong = "000000" if code != "000000" else "111111"

    for _ in range(MAX_CODE_ATTEMPTS - 1):
        assert status(accounts.confirm, "ann@example.com", wrong) == 400
    assert status(accounts.confirm, "ann@example.com", wrong) == 429
    assert status(accounts.confirm, "ann@example.com", code) == 400  # used up: "send a new one"

    assert status(accounts.resend_code, "ann@example.com") == 429  # too soon after the last one
    clock.now += CODE_RESEND_AFTER
    accounts.resend_code("ann@example.com")
    clock.now += CODE_TTL + timedelta(seconds=1)
    assert status(accounts.confirm, "ann@example.com", last_code(smtp)) == 400  # expired

    clock.now += CODE_RESEND_AFTER
    accounts.resend_code("ann@example.com")
    accounts.confirm("ann@example.com", last_code(smtp))


def test_new_codes_only_for_unconfirmed_accounts(tmp_path):
    clock = Clock()
    accounts, smtp = make_accounts(tmp_path, clock=clock)
    accounts.resend_code("nobody@example.com")  # quietly nothing: the answer doesn't reveal accounts
    assert smtp.sent == []

    accounts.register("Ann", "ann@example.com", "first password")
    clock.now += CODE_RESEND_AFTER
    # Registering again before confirming replaces the password and sends a new code.
    accounts.register("Ann B", "ann@example.com", "second password")
    accounts.confirm("ann@example.com", last_code(smtp))
    assert status(accounts.sign_in, "ann@example.com", "first password") == 401
    assert accounts.sign_in("ann@example.com", "second password")[0].name == "Ann B"

    sent = len(smtp.sent)
    clock.now += CODE_RESEND_AFTER
    accounts.resend_code("ann@example.com")  # confirmed: nothing to send
    assert len(smtp.sent) == sent


def test_unconfirmed_addresses_are_forgotten(tmp_path):
    clock = Clock()
    accounts, smtp = make_accounts(tmp_path, clock=clock)
    accounts.register("Ann", "ann@example.com", "long enough")
    clock.now += UNCONFIRMED_KEEP
    accounts.register("Bob", "bob@example.com", "long enough")
    assert status(accounts.confirm, "ann@example.com", "123456") == 404


def test_codes_per_hour_are_capped(tmp_path):
    clock = Clock()
    accounts, smtp = make_accounts(tmp_path, clock=clock)
    for n in range(MAX_CODES_PER_HOUR):
        accounts.register("Someone", f"user{n}@example.com", "long enough")
    assert status(accounts.register, "One more", "late@example.com", "long enough") == 429
    assert len(smtp.sent) == MAX_CODES_PER_HOUR
    clock.now += timedelta(hours=1)
    accounts.register("One more", "late@example.com", "long enough")


def test_a_failed_email_keeps_no_account(tmp_path):
    accounts, _ = make_accounts(tmp_path, smtp=FakeSmtp(fail="login"))
    with pytest.raises(AccountsError, match="Couldn't send the email") as error:
        accounts.register("Ann", "ann@example.com", "long enough")
    assert error.value.status == 502
    assert status(accounts.confirm, "ann@example.com", "123456") == 404


def test_wrong_passwords_lock_the_account_for_a_while(tmp_path):
    clock = Clock()
    accounts, smtp = make_accounts(tmp_path, clock=clock)
    accounts.register("Ann", "ann@example.com", "long enough")
    accounts.confirm("ann@example.com", last_code(smtp))

    for _ in range(MAX_FAILURES):
        with pytest.raises(AccountsError, match="Wrong email or password") as error:
            accounts.sign_in("ann@example.com", "wrong password")
        assert error.value.status == 401
    assert status(accounts.sign_in, "ann@example.com", "long enough") == 429  # even the right password waits

    clock.now += LOCKOUT
    accounts.sign_in("ann@example.com", "long enough")

    # An unknown address gets the same answer as a wrong password.
    with pytest.raises(AccountsError, match="Wrong email or password"):
        accounts.sign_in("nobody@example.com", "long enough")


def test_sessions_expire(tmp_path):
    clock = Clock()
    accounts, smtp = make_accounts(tmp_path, clock=clock)
    accounts.register("Ann", "ann@example.com", "long enough")
    _, token = accounts.confirm("ann@example.com", last_code(smtp))
    clock.now += timedelta(days=SESSION_DAYS, seconds=1)
    assert accounts.account_for(token) is None


def test_the_file_holds_no_passwords_codes_or_tokens(tmp_path):
    accounts, smtp = make_accounts(tmp_path)
    accounts.register("Ann", "ann@example.com", "long enough")
    code = last_code(smtp)
    saved = (tmp_path / "users.json").read_text(encoding="utf-8")
    assert "ann@example.com" in saved and "long enough" not in saved and code not in saved

    _, token = accounts.confirm("ann@example.com", code)
    assert token not in (tmp_path / "users.json").read_text(encoding="utf-8")


def make_client(tmp_path, mail=True):
    store = DeviceStore(get_profile("pothos"), lambda device_id: False, lambda: T0)
    accounts, smtp = make_accounts(tmp_path, mail=mail)
    return TestClient(create_app(store, ChatAgent(store), None, "greenpulse-01", accounts=accounts)), smtp


def test_the_api_needs_a_signed_in_session(tmp_path):
    client, smtp = make_client(tmp_path)
    assert client.get("/api/devices").status_code == 401
    assert client.get("/api/auth/me").json() == {"account": None, "registration_open": True}

    registered = client.post("/api/auth/register", json={"name": "Ann", "email": "Ann@example.com", "password": "long enough"})
    assert registered.status_code == 201 and registered.json() == {"email": "ann@example.com"}
    assert "set-cookie" not in registered.headers  # not signed in until confirmed

    early = client.post("/api/auth/login", json={"email": "ann@example.com", "password": "long enough"})
    assert early.status_code == 403 and early.json()["reason"] == "unconfirmed"
    assert client.post("/api/auth/confirm", json={"email": "ann@example.com", "code": "12345"}).status_code == 422
    assert client.post("/api/auth/code", json={"email": "someone@example.com"}).json() == {"ok": True}

    confirmed = client.post("/api/auth/confirm", json={"email": "ann@example.com", "code": last_code(smtp)})
    assert confirmed.status_code == 200 and confirmed.json()["account"]["name"] == "Ann"
    assert client.get("/api/devices").status_code == 200
    assert client.get("/api/auth/me").json()["account"]["email"] == "ann@example.com"

    client.post("/api/auth/logout")
    assert client.get("/api/devices").status_code == 401

    wrong = client.post("/api/auth/login", json={"email": "ann@example.com", "password": "nope"})
    assert wrong.status_code == 401 and wrong.json() == {"detail": "Wrong email or password."}
    assert client.post("/api/auth/login", json={"email": "ann@example.com", "password": "long enough"}).status_code == 200
    assert client.get("/api/devices").status_code == 200


def test_registration_closed_without_email(tmp_path):
    client, _ = make_client(tmp_path, mail=False)
    assert client.get("/api/auth/me").json()["registration_open"] is False
    response = client.post("/api/auth/register", json={"name": "Ann", "email": "ann@example.com", "password": "long enough"})
    assert response.status_code == 503 and "Registration is closed" in response.json()["detail"]


def test_session_cookie_flags(tmp_path):
    client, smtp = make_client(tmp_path)
    client.post("/api/auth/register", json={"name": "Ann", "email": "ann@example.com", "password": "long enough"})
    cookie = client.post("/api/auth/confirm", json={"email": "ann@example.com", "code": last_code(smtp)}).headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=") and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Secure" not in cookie  # plain http while developing

    # Behind Nginx (HTTPS), the cookie is only ever sent over HTTPS.
    https = client.post(
        "/api/auth/login",
        json={"email": "ann@example.com", "password": "long enough"},
        headers={"x-forwarded-proto": "https"},
    )
    assert "Secure" in https.headers["set-cookie"]
