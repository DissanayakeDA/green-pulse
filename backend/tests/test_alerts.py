import json
import re
from datetime import datetime, timedelta, timezone

import pytest

from greenpulse_ai import Settings, build_service
from greenpulse_ai.alerts import AlertCenter, AlertsError
from greenpulse_ai.device_state import DeviceStore
from greenpulse_ai.mailer import HEADER, Mailer
from greenpulse_ai.plant_profiles import get_profile
from greenpulse_ai.watering import WateringDecision

from conftest import T0, FakeSmtp, reading


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)


def make_center(tmp_path, smtp=None, clock=None, mailer=True):
    smtp = smtp or FakeSmtp()
    clock = clock or Clock()
    store = DeviceStore(get_profile("pothos"), clock=clock)
    sender = Mailer("smtppro.zoho.com", 465, "hello@kyndexlab.com", "app-password", connect=smtp) if mailer else None
    center = AlertCenter(sender, store, tmp_path / "alerts.json", "Asia/Colombo", 8, "http://dash.example", clock)
    return center, smtp, clock


def code_in(message) -> str:
    return re.match(r"(\d{6}) is your GreenPulse code", message["Subject"]).group(1)


def confirmed(center, smtp, email="owner@example.com") -> dict:
    recipient = center.add(email)
    return center.verify(recipient["id"], code_in(smtp.sent[-1]))


def result(priority="high", headline=None, device_id="greenpulse-01"):
    care = build_service(Settings(offline=True), None).handle_reading(reading(moisture=18.0, device_id=device_id))
    update = {"priority": priority} | ({"headline": headline} if headline else {})
    return care.model_copy(update={"generated_at": T0, "advice": care.advice.model_copy(update=update)})


def alerts_sent(center, smtp) -> list:
    smtp.sent.clear()
    center.send_pending()
    return [m for m in smtp.sent if m[HEADER] == "alert"]


# --------------------------------------------------------------------------- signing up


def test_a_new_address_gets_nothing_until_it_is_confirmed(tmp_path):
    center, smtp, _ = make_center(tmp_path)
    recipient = center.add("  owner@example.com ")

    assert recipient["email"] == "owner@example.com"
    assert recipient["verified"] is False and recipient["code_pending"] is True
    assert "code_hash" not in recipient
    message = smtp.sent[-1]
    assert message["To"] == "owner@example.com"
    assert message["From"] == "GreenPulse <hello@kyndexlab.com>"
    assert message[HEADER] == "code"
    assert smtp.connections == [("smtppro.zoho.com", 465)]

    center.on_result(result("critical"))
    assert alerts_sent(center, smtp) == []

    code = code_in(message)
    with pytest.raises(AlertsError, match="isn't right") as wrong:
        center.verify(recipient["id"], "000000" if code != "000000" else "111111")
    assert wrong.value.status == 400
    assert center.verify(recipient["id"], f" {code} ")["verified"] is True


def test_bad_and_duplicate_addresses_are_refused(tmp_path):
    center, _, _ = make_center(tmp_path)
    center.add("owner@example.com")
    for bad in ("not-an-email", "a@b", "two words@example.com", "x@example.com\r\nBcc: spam@example.com"):
        with pytest.raises(AlertsError) as error:
            center.add(bad)
        assert error.value.status == 422
    with pytest.raises(AlertsError, match="already on the list"):
        center.add("OWNER@example.com")


def test_codes_expire_and_wrong_guesses_are_limited(tmp_path):
    center, smtp, clock = make_center(tmp_path)
    recipient = center.add("owner@example.com")
    code = code_in(smtp.sent[-1])
    wrong = "000000" if code != "000000" else "111111"

    for _ in range(4):
        with pytest.raises(AlertsError, match="isn't right"):
            center.verify(recipient["id"], wrong)
    with pytest.raises(AlertsError, match="Too many wrong codes") as error:
        center.verify(recipient["id"], wrong)
    assert error.value.status == 429
    with pytest.raises(AlertsError, match="expired"):
        center.verify(recipient["id"], code)  # the right code is dead too now

    clock.advance(seconds=61)
    center.resend_code(recipient["id"])
    clock.advance(minutes=16)
    with pytest.raises(AlertsError, match="expired"):
        center.verify(recipient["id"], code_in(smtp.sent[-1]))


def test_a_new_code_waits_a_minute_and_replaces_the_old_one(tmp_path):
    center, smtp, clock = make_center(tmp_path)
    recipient = center.add("owner@example.com")
    first = code_in(smtp.sent[-1])

    with pytest.raises(AlertsError, match="Wait 60 s") as error:
        center.resend_code(recipient["id"])
    assert error.value.status == 429

    clock.advance(seconds=60)
    center.resend_code(recipient["id"])
    second = code_in(smtp.sent[-1])
    if first != second:
        with pytest.raises(AlertsError, match="isn't right"):
            center.verify(recipient["id"], first)
    assert center.verify(recipient["id"], second)["verified"] is True


def test_codes_per_hour_are_limited_for_everyone(tmp_path):
    center, _, clock = make_center(tmp_path)
    for i in range(10):
        center.add(f"person{i}@example.com")
    center.remove(center.overview()["recipients"][0]["id"])
    with pytest.raises(AlertsError, match="Too many codes") as error:
        center.add("one.more@example.com")
    assert error.value.status == 429
    assert len(center.overview()["recipients"]) == 9

    clock.advance(hours=1)
    center.add("one.more@example.com")


def test_if_the_code_cant_be_sent_nobody_is_added(tmp_path):
    center, _, _ = make_center(tmp_path, smtp=FakeSmtp(fail="login"))
    with pytest.raises(AlertsError, match="refused the login for hello@kyndexlab.com") as error:
        center.add("owner@example.com")
    assert error.value.status == 502

    overview = center.overview()
    assert overview["recipients"] == []
    assert overview["recent"][0]["ok"] is False and overview["recent"][0]["kind"] == "code"


def test_without_smtp_nothing_is_sent(tmp_path):
    center, _, _ = make_center(tmp_path, mailer=False)
    assert center.overview()["configured"] is False
    with pytest.raises(AlertsError, match="SMTP_HOST") as error:
        center.add("owner@example.com")
    assert error.value.status == 503
    center.on_result(result("critical"))  # no error, nothing queued
    center.send_pending()


def test_test_email(tmp_path):
    center, smtp, clock = make_center(tmp_path)
    recipient = center.add("owner@example.com")
    with pytest.raises(AlertsError, match="Confirm the address") as error:
        center.send_test(recipient["id"])
    assert error.value.status == 409

    center.verify(recipient["id"], code_in(smtp.sent[-1]))
    center.update(recipient["id"], alerts=True, min_priority="critical", daily=False)
    center.send_test(recipient["id"])
    message = smtp.sent[-1]
    assert message[HEADER] == "test"
    assert "plant alerts at critical priority" in message.get_body(("plain",)).get_content()

    with pytest.raises(AlertsError, match="just sent"):
        center.send_test(recipient["id"])
    clock.advance(seconds=60)
    center.send_test(recipient["id"])


def test_the_list_survives_a_restart(tmp_path):
    center, smtp, clock = make_center(tmp_path)
    owner = confirmed(center, smtp)
    center.update(owner["id"], alerts=False, min_priority="critical", daily=True)
    pending = center.add("friend@example.com")
    code = code_in(smtp.sent[-1])

    saved = (tmp_path / "alerts.json").read_text(encoding="utf-8")
    assert code not in saved  # only a hash of the code is kept

    again = AlertCenter(center.mailer, center.store, tmp_path / "alerts.json", clock=clock)
    assert again.overview()["recipients"] == center.overview()["recipients"]
    assert again.verify(pending["id"], code)["verified"] is True


# --------------------------------------------------------------------------- plant alerts


def test_alerts_only_when_it_matters(tmp_path):
    center, smtp, clock = make_center(tmp_path)
    confirmed(center, smtp)

    center.on_result(result("medium"))
    assert alerts_sent(center, smtp) == []

    center.on_result(result("high"))
    [first] = alerts_sent(center, smtp)
    assert first["Subject"].startswith("Act within 2 hours: ")

    clock.advance(minutes=5)
    center.on_result(result("high"))
    assert alerts_sent(center, smtp) == []  # same problem, already told

    clock.advance(minutes=5)
    center.on_result(result("critical"))
    [worse] = alerts_sent(center, smtp)
    assert worse["Subject"].startswith("Act now: ")
    assert "It has got worse" in worse.get_body(("plain",)).get_content()

    clock.advance(hours=6)
    center.on_result(result("critical"))
    [still] = alerts_sent(center, smtp)
    assert still["Subject"].startswith("Reminder: Act now: ")

    clock.advance(minutes=10)
    center.on_result(result("medium"))  # fixed...
    clock.advance(minutes=20)
    center.on_result(result("high"))  # ...but back within the hour: flickering, no email
    assert alerts_sent(center, smtp) == []

    clock.advance(minutes=40)
    center.on_result(result("high"))
    assert len(alerts_sent(center, smtp)) == 1  # a new problem, over an hour after the last email


def test_each_person_chooses_their_alerts(tmp_path):
    center, smtp, clock = make_center(tmp_path)
    confirmed(center, smtp, "all@example.com")
    critical_only = confirmed(center, smtp, "critical@example.com")
    center.update(critical_only["id"], alerts=True, min_priority="critical", daily=True)
    no_alerts = confirmed(center, smtp, "summary-only@example.com")
    center.update(no_alerts["id"], alerts=False, min_priority="high", daily=True)
    center.add("unconfirmed@example.com")

    center.on_result(result("high"))
    assert [m["To"] for m in alerts_sent(center, smtp)] == ["all@example.com"]

    clock.advance(minutes=5)
    center.on_result(result("critical"))
    assert sorted(m["To"] for m in alerts_sent(center, smtp)) == ["all@example.com", "critical@example.com"]


def test_each_device_has_its_own_alerts(tmp_path):
    center, smtp, _ = make_center(tmp_path)
    confirmed(center, smtp)
    center.on_result(result("high", device_id="greenpulse-01"))
    center.on_result(result("high", device_id="greenpulse-02"))
    assert len(alerts_sent(center, smtp)) == 2


def test_alert_email_content(tmp_path):
    center, smtp, _ = make_center(tmp_path)
    confirmed(center, smtp)
    decision = WateringDecision(True, "Soil at 18% is below 40% and the Plant Doctor rates it critical", True, 5.0)
    center.on_result(result("critical", headline="Water <b>now</b>"), decision)
    [message] = alerts_sent(center, smtp)

    assert message["Subject"] == "Act now: Water <b>now</b> - Pothos (Money Plant)"
    assert message["Auto-Submitted"] == "auto-generated"
    text = message.get_body(("plain",)).get_content()
    assert "Pothos (Money Plant) (greenpulse-01) needs attention." in text
    assert "Soil moisture: 18% (far too low; ideal 35-65%)" in text
    assert "Auto-watering: watering now (5 s pulse)." in text
    assert "Checked 29 Sep, 14:30." in text  # Colombo time
    assert "http://dash.example/alerts" in text
    html = message.get_body(("html",)).get_content()
    assert "Water &lt;b&gt;now&lt;/b&gt;" in html and "<b>now</b>" not in html


# --------------------------------------------------------------------------- scheduled emails


def test_daily_summary_once_a_day_at_the_chosen_hour(tmp_path):
    clock = Clock(datetime(2026, 9, 30, 2, 29, tzinfo=timezone.utc))  # 07:59 in Colombo
    center, smtp, _ = make_center(tmp_path, clock=clock)
    confirmed(center, smtp, "daily@example.com")
    no_summary = confirmed(center, smtp, "alerts-only@example.com")
    center.update(no_summary["id"], alerts=True, min_priority="high", daily=False)
    center.store.record_reading(reading(moisture=18.0, device_id="greenpulse-01").model_copy(update={"timestamp": clock.now}))
    center.store.record_result(result("high"))
    center.store.record_pump_state("greenpulse-01", {"state": "on", "source": "auto", "duration_s": 5})

    def summaries():
        smtp.sent.clear()
        center.tick()
        center.send_pending()
        return [m for m in smtp.sent if m[HEADER] == "daily"]

    assert summaries() == []
    clock.advance(minutes=1)  # 08:00
    [summary] = summaries()
    assert summary["To"] == "daily@example.com"
    assert summary["Subject"] == "GreenPulse daily summary - 30 Sep"
    text = summary.get_body(("plain",)).get_content()
    assert "Pothos (Money Plant) (greenpulse-01) - online" in text
    assert "Act within 2 hours: " in text
    assert "Watered 1 time in the last 24 h (1 automatic, 0 manual)." in text

    clock.advance(minutes=30)
    assert summaries() == []  # once a day
    clock.advance(hours=24)
    assert len(summaries()) == 1
    assert json.loads((tmp_path / "alerts.json").read_text())["last_daily"] == "2026-10-01"


def test_offline_device_is_reported_once_per_outage(tmp_path):
    center, smtp, clock = make_center(tmp_path)
    confirmed(center, smtp)
    center.store.record_reading(reading(device_id="greenpulse-01"))

    def offline_emails():
        smtp.sent.clear()
        center.tick()
        center.send_pending()
        return [m for m in smtp.sent if m[HEADER] == "offline"]

    clock.advance(minutes=14)
    assert offline_emails() == []
    clock.advance(minutes=2)
    [message] = offline_emails()
    assert message["Subject"] == "Device offline - greenpulse-01 has stopped reporting"
    assert offline_emails() == []

    center.store.record_reading(reading(device_id="greenpulse-01"))  # back online
    assert offline_emails() == []
    clock.advance(minutes=16)
    assert len(offline_emails()) == 1
