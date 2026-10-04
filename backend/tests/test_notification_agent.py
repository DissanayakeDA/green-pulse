import dataclasses
import imaplib
from datetime import date

import pytest

from greenpulse_ai import Settings, live_context_agents
from greenpulse_ai.agents import ImapNotificationAgent, NoMailboxAgent, OpenMeteoWeatherAgent
from greenpulse_ai.agents.notification import find_reminders, parse_email

from conftest import T0, FakeImap, make_email


def message(subject, body="", sender="someone@example.com"):
    return {"from": sender, "subject": subject, "body": body}


@pytest.mark.parametrize(
    "subject, kind",
    [
        ("Water the pothos tonight", "watering"),
        ("Watering reminder: Money plant", "watering"),
        ("Time to fertilise", "fertilising"),
        ("Fertilizer delivery", "fertilising"),
        ("Repotting checklist", "repotting"),
        ("Repot and water the fern", "repotting"),  # the more specific kind wins
        ("Your flight to Dubai", "travel"),
        ("Booking confirmed: Kandy trip", "travel"),
    ],
)
def test_reminder_kinds(subject, kind):
    report = find_reminders([message(subject)], "email")
    assert [r.kind for r in report.reminders] == [kind]


@pytest.mark.parametrize("subject", ["Waterproof speaker sale", "Rainwater tank offer", "Tripod deals", "Weekly newsletter"])
def test_only_whole_words_match(subject):
    report = find_reminders([message(subject)], "email")
    assert report.reminders == []
    assert report.summary == "No plant-care reminders or travel plans among 1 recent messages."


def test_reminder_detail_is_compacted_and_capped():
    report = find_reminders([message("Water the plant", "line one\n\n   line two " + "x" * 500)], "email")
    detail = report.reminders[0].detail
    assert detail.startswith("line one line two x")
    assert len(detail) == 300


def test_at_most_five_reminders():
    report = find_reminders([message(f"Water plant {n}") for n in range(8)], "email")
    assert len(report.reminders) == 5


def test_parse_plain_text_email():
    parsed = parse_email(make_email("Watering reminder", "Water the money plant today.", hours_ago=2))
    assert parsed["subject"] == "Watering reminder"
    assert parsed["from"] == "reminders@plantdiary.example.com"
    assert parsed["body"].strip() == "Water the money plant today."
    assert parsed["received"].tzinfo is not None
    assert parsed["received"].isoformat() == "2026-09-29T07:00:00+00:00"


def test_parse_prefers_plain_text_over_html():
    parsed = parse_email(make_email("Reminder", "Plain version", html="<p>HTML version</p>"))
    assert parsed["body"].strip() == "Plain version"


def test_parse_html_only_email():
    html = "<html><style>p {color: red}</style><body><p>Fertilise &amp; water</p><script>alert(1)</script></body></html>"
    parsed = parse_email(make_email("Reminder", "", html=html))
    assert " ".join(parsed["body"].split()) == "Fertilise & water"


def mailbox(*messages, **kwargs):
    imap = FakeImap(list(messages), **kwargs)
    clock = {"now": 1000.0}
    agent = ImapNotificationAgent(
        "imap.gmail.com",
        "plant.owner@gmail.com",
        "app-password",
        connect=imap,
        clock=lambda: clock["now"],
        today=lambda: date(2026, 9, 29),
    )
    return agent, imap, clock


def test_reads_the_mailbox_without_changing_it():
    agent, imap, _ = mailbox(
        make_email("Weekend sale: 30% off headphones", "Waterproof and wireless.", sender="deals@shop.example.com", hours_ago=5),
        make_email("Watering reminder: Money plant", "Your money plant is due for watering tomorrow.", hours_ago=1),
    )
    report = agent.run()

    assert report.source == "email"
    assert [r.title for r in report.reminders] == ["Watering reminder: Money plant"]
    assert report.summary == "Relevant messages: Watering reminder: Money plant (watering)."
    assert ("login", "plant.owner@gmail.com") in imap.calls
    assert ("select", '"INBOX"', True) in imap.calls  # read-only
    assert ("search", "SINCE", "22-Sep-2026") in imap.calls  # the last 7 days
    fetch = next(call for call in imap.calls if call[0] == "fetch")
    assert "BODY.PEEK[]" in fetch[2]  # PEEK: messages stay unread
    assert imap.calls[-1] == ("logout",)


def test_newest_messages_first():
    agent, _, _ = mailbox(
        make_email("Water the plant (older)", "", html="<p>older</p>", hours_ago=30),
        make_email("Water the plant (newer)", "newer", hours_ago=1),
    )
    titles = [r.title for r in agent.run().reminders]
    assert titles == ["Water the plant (newer)", "Water the plant (older)"]


def test_empty_mailbox():
    agent, imap, _ = mailbox()
    report = agent.run()
    assert report.reminders == []
    assert "among 0 recent messages" in report.summary
    assert not any(call[0] == "fetch" for call in imap.calls)


def test_mailbox_result_is_cached():
    agent, imap, clock = mailbox(make_email("Water the plant", "today"))
    agent.run()
    clock["now"] += 300
    agent.run()
    assert imap.connections() == 1
    clock["now"] += 400  # past the 10 min cache
    agent.run()
    assert imap.connections() == 2


def test_wrong_password_raises():
    # The orchestrator turns the error into a "notifications unavailable" report.
    agent, imap, _ = mailbox(make_email("Water the plant", "today"), password="something-else")
    with pytest.raises(imaplib.IMAP4.error):
        agent.run()
    assert imap.calls[-1] == ("logout",)


def test_a_failed_check_reuses_the_last_result():
    agent, imap, clock = mailbox(make_email("Water the plant", "today"))
    first = agent.run()
    imap.password = "revoked"
    clock["now"] += 3600
    assert agent.run() == first


def test_unknown_folder():
    imap = FakeImap([], folders=("INBOX",))
    agent = ImapNotificationAgent("imap.gmail.com", "a@gmail.com", "app-password", folder="Plants", connect=imap)
    with pytest.raises(RuntimeError, match="Plants"):
        agent.run()


def test_no_mailbox_configured():
    report = NoMailboxAgent().run()
    assert report.source == "not-configured"
    assert report.reminders == []


def test_live_context_agents():
    settings = Settings(location="Kandy, LK", weather_latitude=7.29, weather_longitude=80.63)
    weather, notifications = live_context_agents(settings)
    assert isinstance(weather, OpenMeteoWeatherAgent)
    assert (weather.params["latitude"], weather.params["longitude"]) == (7.29, 80.63)
    assert isinstance(notifications, NoMailboxAgent)

    with_email = dataclasses.replace(settings, email_address="a@gmail.com", email_app_password="abcdefghijklmnop")
    _, notifications = live_context_agents(with_email)
    assert isinstance(notifications, ImapNotificationAgent)
    assert (notifications.host, notifications.username, notifications.folder) == ("imap.gmail.com", "a@gmail.com", "INBOX")


def test_email_settings_from_env(monkeypatch):
    monkeypatch.setattr("greenpulse_ai.config.load_dotenv", lambda: None)  # ignore the developer's .env
    monkeypatch.setenv("EMAIL_ADDRESS", "a@gmail.com")
    monkeypatch.setenv("EMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")
    settings = Settings.from_env()
    assert settings.email_app_password == "abcdefghijklmnop"  # Gmail shows it with spaces
    assert "abcd" not in repr(settings)  # never printed or logged


def test_reminder_timestamps_survive_json():
    agent, _, _ = mailbox(make_email("Water the plant", "today", hours_ago=3))
    payload = agent.run().model_dump(mode="json")
    assert payload["reminders"][0]["received"].startswith(T0.replace(hour=6).strftime("%Y-%m-%dT%H:%M:%S"))
