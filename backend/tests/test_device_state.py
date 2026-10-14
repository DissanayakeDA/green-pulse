from datetime import timedelta

from greenpulse_ai import Settings, build_pipeline
from greenpulse_ai.device_state import DeviceStore
from greenpulse_ai.plant_profiles import get_profile
from greenpulse_ai.watering import WateringDecision

from conftest import T0, reading


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)


def make_store(auto_watering=False):
    clock = Clock()
    return DeviceStore(get_profile("pothos"), lambda device_id: auto_watering, clock), clock


def test_unknown_device_has_an_empty_snapshot():
    store, _ = make_store()
    snapshot = store.snapshot("greenpulse-01")
    assert snapshot["reading"] is None and snapshot["metrics"] is None and snapshot["analysis"] is None
    assert snapshot["online"] is False
    assert snapshot["plant"]["name"] == "Pothos (Money Plant)"
    assert store.devices() == []


def test_snapshot_classifies_the_latest_reading_and_the_trend():
    store, clock = make_store()
    for minutes, moisture in ((0, 50.0), (30, 46.0), (60, 42.0)):
        clock.now = T0 + timedelta(minutes=minutes)
        store.record_reading(reading(minutes, moisture=moisture, device_id="d1"))

    snapshot = store.snapshot("d1")
    assert snapshot["online"]
    assert snapshot["reading"]["soil_moisture"] == 42.0
    assert snapshot["metrics"]["soil_moisture"]["state"] == "optimal"
    assert snapshot["metrics"]["temperature"]["ideal_min"] == 18
    assert snapshot["moisture_trend_per_hour"] == -8.0
    assert snapshot["hours_until_dry"] == 0.9
    assert snapshot["sensor_priority"] == "high"  # dry in under 2 h


def test_device_goes_offline_after_90_s_without_a_reading():
    store, clock = make_store()
    store.record_reading(reading(device_id="d1"))
    clock.advance(seconds=60)
    assert store.snapshot("d1")["online"]
    clock.advance(seconds=60)
    assert not store.snapshot("d1")["online"]
    assert store.devices() == [{"device_id": "d1", "online": False, "last_seen": "2026-09-29T09:00:00+00:00"}]


def test_readings_older_than_a_day_are_dropped():
    store, clock = make_store()
    store.record_reading(reading(0, device_id="d1"))
    clock.advance(hours=25)
    store.record_reading(reading(25 * 60, device_id="d1"))
    assert len(store.readings("d1", hours=48)) == 1


def test_history_averages_buckets_and_keeps_gaps():
    store, clock = make_store()
    clock.now = T0 + timedelta(hours=2)
    for minutes, moisture in ((0, 50.0), (10, 48.0), (20, 46.0), (100, 40.0)):
        store.record_reading(reading(minutes, moisture=moisture, device_id="d1"))
    store.record_pump_state("d1", {"state": "on", "source": "auto", "duration_s": 5}, T0 + timedelta(minutes=95))

    history = store.history("d1", hours=2, buckets=4)
    assert [p["soil_moisture"] for p in history["points"]] == [48.0, None, None, 40.0]
    assert history["points"][0]["t"] == int((T0 + timedelta(minutes=15)).timestamp() * 1000)
    assert history["waterings"] == [
        {"t": int((T0 + timedelta(minutes=95)).timestamp() * 1000), "source": "auto", "seconds": 5.0}
    ]


def test_pump_events_and_the_watering_summary():
    store, clock = make_store(auto_watering=True)
    store.record_pump_state("d1", {"state": "on", "source": "manual", "duration_s": 5, "reason": "Dashboard button"})
    watering = store.snapshot("d1")["watering"]
    assert watering["pump_running"] and watering["auto_enabled"]
    assert watering["last_watered"] == "2026-09-29T09:00:00+00:00"

    clock.advance(seconds=5)
    store.record_pump_state("d1", {"state": "off", "source": "manual", "ran_s": 5.0, "result": "done"})
    store.record_pump_state("d1", {"state": "rejected", "source": "auto", "detail": "pump is resting, 55 s left"})
    store.record_pump_state("d1", {"state": "exploded"})  # not a pump state: ignored

    watering = store.snapshot("d1")["watering"]
    assert not watering["pump_running"]
    assert [e["state"] for e in watering["events"]] == ["rejected", "off", "on"]  # newest first
    assert watering["events"][0]["detail"] == "pump is resting, 55 s left"
    assert watering["events"][1]["seconds"] == 5.0


def test_a_lost_off_message_does_not_leave_the_pump_running():
    store, clock = make_store()
    store.record_pump_state("d1", {"state": "on", "source": "auto", "duration_s": 5})
    clock.advance(seconds=11)
    assert not store.snapshot("d1")["watering"]["pump_running"]


def test_the_last_plant_doctor_result_is_shown():
    store, _ = make_store()
    result = build_pipeline(Settings(offline=True), None).run(reading(moisture=20.0, device_id="d1"))
    store.record_result(result, WateringDecision(False, "Auto-watering is off", False))

    snapshot = store.snapshot("d1")
    analysis = snapshot["analysis"]
    assert analysis["priority"] == "critical" and analysis["priority_code"] == 3
    assert analysis["headline"] == "Water now"
    assert analysis["source"] == "rules"
    assert analysis["weather"]["summary"] and "agent" not in analysis["weather"]
    assert snapshot["watering"]["last_decision"]["reason"] == "Auto-watering is off"
