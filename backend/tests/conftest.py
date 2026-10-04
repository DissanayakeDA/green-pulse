import imaplib
import sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

import pytest
from langchain_core.runnables import RunnableLambda

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenpulse_ai.plant_profiles import get_profile  # noqa: E402
from greenpulse_ai.schemas import SensorReading  # noqa: E402

T0 = datetime(2026, 9, 29, 9, 0, tzinfo=timezone.utc)


def reading(minutes: float = 0, moisture=50.0, temperature=26.0, humidity=60.0, device_id="test-01") -> SensorReading:
    return SensorReading(
        device_id=device_id,
        timestamp=T0 + timedelta(minutes=minutes),
        soil_moisture=moisture,
        temperature=temperature,
        humidity=humidity,
    )


class FakeLLM:
    """Stands in for a LangChain chat model: with_structured_output(schema) returns a canned object
    (or raises a canned exception) and records the prompt it was given."""

    def __init__(self, responses: dict):
        self.responses = responses
        self.prompts: dict[type, list] = {}

    def with_structured_output(self, schema, **_):
        def respond(prompt_value):
            self.prompts.setdefault(schema, []).append(prompt_value.to_messages())
            response = self.responses[schema]
            if isinstance(response, Exception):
                raise response
            return response

        return RunnableLambda(respond)


def open_meteo_response(temperature=29.4, humidity=71, code=3, hourly_temps=(29.4, 30.1, 28.0), rain=(94, 60, 8)) -> dict:
    """The shape of a real https://api.open-meteo.com/v1/forecast response (current + hourly)."""
    return {
        "timezone": "Asia/Colombo",
        "current": {"time": "2026-09-29T15:30", "temperature_2m": temperature, "relative_humidity_2m": humidity, "weather_code": code},
        "hourly": {
            "time": [f"2026-09-29T{15 + i}:00" for i in range(len(hourly_temps))],
            "temperature_2m": list(hourly_temps),
            "precipitation_probability": list(rain),
        },
    }


def make_email(subject: str, body: str, sender="reminders@plantdiary.example.com", html: str | None = None, hours_ago=1.0) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "plant.owner@example.com"
    message["Subject"] = subject
    message["Date"] = format_datetime(T0 - timedelta(hours=hours_ago))
    if body:
        message.set_content(body)
    if html:
        if body:
            message.add_alternative(html, subtype="html")
        else:
            message.set_content(html, subtype="html")
    return bytes(message)


class FakeImap:
    """Stands in for imaplib.IMAP4_SSL: serves `messages` (oldest first) and records every call."""

    def __init__(self, messages: list[bytes], password="app-password", folders=("INBOX",)):
        self.messages = messages
        self.password = password
        self.folders = folders
        self.calls: list[tuple] = []

    def __call__(self, host, timeout=None):  # the "connect" function
        self.calls.append(("connect", host))
        return self

    def login(self, username, password):
        self.calls.append(("login", username))
        if password != self.password:
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox, readonly))
        return ("OK", [str(len(self.messages)).encode()]) if mailbox.strip('"') in self.folders else ("NO", [b"Unknown"])

    def search(self, charset, *criteria):
        self.calls.append(("search", *criteria))
        return "OK", [" ".join(str(i + 1) for i in range(len(self.messages))).encode()]

    def fetch(self, message_set, parts):
        self.calls.append(("fetch", message_set, parts))
        data = []
        for seq in message_set.split(","):
            raw = self.messages[int(seq) - 1]
            data += [(f"{seq} (BODY[]<0> {{{len(raw)}}}".encode(), raw), b")"]
        return "OK", data

    def logout(self):
        self.calls.append(("logout",))

    def connections(self) -> int:
        return sum(1 for call in self.calls if call[0] == "connect")


@pytest.fixture
def pothos():
    return get_profile("pothos")
