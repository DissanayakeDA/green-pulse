from datetime import timedelta

import pytest

from greenpulse_ai import Settings, build_pipeline
from greenpulse_ai.watering import WateringPolicy

from conftest import T0, reading

PIPELINE = build_pipeline(Settings(offline=True), None)  # pothos: ideal soil 35-65 %


def analyse(moisture, minutes=0.0, **kwargs):
    return PIPELINE.run(reading(minutes, moisture, **kwargs))


def at(minutes):
    return T0 + timedelta(minutes=minutes)


def policy(**kwargs):
    return WateringPolicy(**{"enabled": True, "pulse_s": 4.0, "cooldown_s": 1800, "max_per_day": 3, **kwargs})


def test_waters_dry_soil_when_the_plant_doctor_agrees():
    decision = policy().decide(analyse(20), at(0))
    assert decision.water
    assert decision.duration_s == 4.0
    assert decision.command() == {"action": "on", "duration_s": 4.0, "source": "auto", "reason": decision.reason}
    assert "20%" in decision.reason


def test_auto_watering_is_off_by_default():
    decision = WateringPolicy().decide(analyse(20), at(0))
    assert not decision.water
    assert decision.as_payload()["decision"] == "skip"


def test_the_dashboard_switch_turns_it_on_per_device():
    p = WateringPolicy()
    p.set_enabled("test-01", True)
    assert p.decide(analyse(20), at(0)).water
    assert not p.is_enabled("other-device")


@pytest.mark.parametrize("moisture", [40, 50, 70, 90])
def test_never_waters_soil_that_is_not_dry(moisture):
    assert not policy().decide(analyse(moisture), at(0)).water


def test_never_waters_on_a_failed_soil_sensor():
    decision = policy().decide(analyse(None), at(0))
    assert not decision.water
    assert "sensor" in decision.reason


def test_needs_high_priority_from_the_plant_doctor():
    result = analyse(30)  # "low" state: the rules say high
    lowered = result.model_copy(update={"advice": result.advice.model_copy(update={"priority": "medium"})})
    assert policy().decide(result, at(0)).water
    assert not policy().decide(lowered, at(0)).water


def test_waits_for_the_last_pulse_to_soak_in():
    p = policy()
    assert p.decide(analyse(20), at(0)).water
    soaking = p.decide(analyse(21, 10), at(10))
    assert not soaking.water and "20 min" in soaking.reason
    assert p.decide(analyse(21, 31), at(31)).water


def test_short_waits_are_shown_in_seconds():
    p = policy(cooldown_s=60)
    p.decide(analyse(20), at(0))
    assert "another 30 s" in p.decide(analyse(20, 0.5), at(0.5)).reason


def test_manual_watering_starts_the_cooldown_too():
    p = policy()
    p.record_pump_state("test-01", {"state": "on", "source": "manual", "duration_s": 5}, at(0))
    assert not p.decide(analyse(20, 5), at(5)).water


def test_a_rejected_auto_run_does_not_count():
    p = policy()
    assert p.decide(analyse(20), at(0)).water
    p.record_pump_state("test-01", {"state": "rejected", "source": "auto", "detail": "pump resting"}, at(0))
    assert p.decide(analyse(20, 1), at(1)).water


def test_confirmed_auto_run_is_not_double_counted():
    p = policy(cooldown_s=60)
    for minute in (0, 2, 4):
        assert p.decide(analyse(20, minute), at(minute)).water
        p.record_pump_state("test-01", {"state": "on", "source": "auto"}, at(minute))
    assert not p.decide(analyse(20, 6), at(6)).water  # max_per_day = 3
    assert p.decide(analyse(20, 60 * 24 + 1), at(60 * 24 + 1)).water  # the first run left the 24 h window


def test_daily_limit_names_the_likely_fault():
    p = policy(cooldown_s=0, max_per_day=1)
    p.decide(analyse(20), at(0))
    decision = p.decide(analyse(20, 1), at(1))
    assert not decision.water and "tank" in decision.reason


def test_from_settings():
    p = WateringPolicy.from_settings(Settings(auto_watering=True, water_pulse_s=3, water_cooldown_s=60))
    assert p.default_enabled and p.pulse_s == 3 and p.cooldown == timedelta(seconds=60)
