from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from greenpulse_ai.accounts import LOCKOUT, MAX_FAILURES, SESSION_COOKIE, SESSION_DAYS, Accounts, AccountsError
from greenpulse_ai.agents.chat import ChatAgent
from greenpulse_ai.api import create_app
from greenpulse_ai.device_state import DeviceStore
from greenpulse_ai.plant_profiles import get_profile

from conftest import T0

CODE = "leafy-garden-42"


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


def make_accounts(tmp_path, code=CODE, clock=None):
    return Accounts(tmp_path / "users.json", code, clock or Clock())


def test_register_sign_in_and_out(tmp_path):
    accounts = make_accounts(tmp_path)
    account, token = accounts.register(" Dumindu ", "Dumindu@Example.com", "correct horse", f" {CODE} ")
    assert (account.name, account.email) == ("Dumindu", "dumindu@example.com")
    assert accounts.account_for(token) == account

    _, second = accounts.sign_in("DUMINDU@example.com ", "correct horse")
    accounts.sign_out(token)
    assert accounts.account_for(token) is None
    assert accounts.account_for(second) == account

    # Accounts and open sessions survive a restart.
    reloaded = make_accounts(tmp_path)
    assert reloaded.count() == 1
    assert reloaded.account_for(second).email == "dumindu@example.com"


def test_registration_rules(tmp_path):
    def status(accounts, name="Ann", email="ann@example.com", password="long enough", code=CODE):
        with pytest.raises(AccountsError) as error:
            accounts.register(name, email, password, code)
        return error.value.status

    assert status(make_accounts(tmp_path, code=None)) == 403  # no code set: registration closed
    accounts = make_accounts(tmp_path)
    assert status(accounts, code="guess") == 403
    assert status(accounts, password="short") == 400
    assert status(accounts, email="not-an-email") == 400
    assert status(accounts, name="  ") == 400

    accounts.register("Ann", "ann@example.com", "long enough", CODE)
    assert status(accounts, email="ANN@example.com") == 409


def test_wrong_passwords_lock_the_account_for_a_while(tmp_path):
    clock = Clock()
    accounts = make_accounts(tmp_path, clock=clock)
    accounts.register("Ann", "ann@example.com", "long enough", CODE)

    for _ in range(MAX_FAILURES):
        with pytest.raises(AccountsError, match="Wrong email or password") as error:
            accounts.sign_in("ann@example.com", "wrong password")
        assert error.value.status == 401
    with pytest.raises(AccountsError) as error:
        accounts.sign_in("ann@example.com", "long enough")  # even the right password waits
    assert error.value.status == 429

    clock.now += LOCKOUT
    accounts.sign_in("ann@example.com", "long enough")

    # An unknown address gets the same answer as a wrong password.
    with pytest.raises(AccountsError, match="Wrong email or password"):
        accounts.sign_in("nobody@example.com", "long enough")


def test_sessions_expire(tmp_path):
    clock = Clock()
    accounts = make_accounts(tmp_path, clock=clock)
    _, token = accounts.register("Ann", "ann@example.com", "long enough", CODE)
    clock.now += timedelta(days=SESSION_DAYS, seconds=1)
    assert accounts.account_for(token) is None


def test_the_file_holds_no_passwords_or_tokens(tmp_path):
    accounts = make_accounts(tmp_path)
    _, token = accounts.register("Ann", "ann@example.com", "long enough", CODE)
    saved = (tmp_path / "users.json").read_text(encoding="utf-8")
    assert "ann@example.com" in saved
    assert "long enough" not in saved and token not in saved


def make_client(tmp_path, code=CODE):
    store = DeviceStore(get_profile("pothos"), lambda device_id: False, lambda: T0)
    accounts = make_accounts(tmp_path, code=code)
    return TestClient(create_app(store, ChatAgent(store), None, "greenpulse-01", accounts=accounts))


def test_the_api_needs_a_signed_in_session(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/api/devices").status_code == 401
    assert client.get("/api/auth/me").json() == {"account": None, "registration_open": True}

    response = client.post(
        "/api/auth/register",
        json={"name": "Ann", "email": "ann@example.com", "password": "long enough", "code": CODE},
    )
    assert response.status_code == 201 and response.json()["account"]["email"] == "ann@example.com"
    assert client.get("/api/devices").status_code == 200
    assert client.get("/api/auth/me").json()["account"]["name"] == "Ann"

    client.post("/api/auth/logout")
    assert client.get("/api/devices").status_code == 401

    wrong = client.post("/api/auth/login", json={"email": "ann@example.com", "password": "nope"})
    assert wrong.status_code == 401 and wrong.json() == {"detail": "Wrong email or password."}
    assert client.post("/api/auth/login", json={"email": "ann@example.com", "password": "long enough"}).status_code == 200
    assert client.get("/api/devices").status_code == 200


def test_closed_registration_is_reported(tmp_path):
    client = make_client(tmp_path, code=None)
    assert client.get("/api/auth/me").json()["registration_open"] is False
    response = client.post(
        "/api/auth/register", json={"name": "Ann", "email": "ann@example.com", "password": "long enough", "code": "x"}
    )
    assert response.status_code == 403 and "Registration is closed" in response.json()["detail"]


def test_session_cookie_flags(tmp_path):
    client = make_client(tmp_path)
    body = {"name": "Ann", "email": "ann@example.com", "password": "long enough", "code": CODE}
    cookie = client.post("/api/auth/register", json=body).headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=") and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Secure" not in cookie  # plain http while developing

    # Behind Nginx (HTTPS), the cookie is only ever sent over HTTPS.
    https = client.post(
        "/api/auth/login",
        json={"email": "ann@example.com", "password": "long enough"},
        headers={"x-forwarded-proto": "https"},
    )
    assert "Secure" in https.headers["set-cookie"]
