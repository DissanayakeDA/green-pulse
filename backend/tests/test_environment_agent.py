import math

import pytest

from greenpulse_ai.agents.environment import METRICS, EnvironmentAgent, classify, hours_until_dry, moisture_trend
from greenpulse_ai.dummy_data import SCENARIOS
from greenpulse_ai.schemas import EnvironmentAssessment

from conftest import FakeLLM, reading


@pytest.mark.parametrize(
    ("value", "expected"),
    [(20, "too_low"), (30, "low"), (35, "optimal"), (65, "optimal"), (70, "high"), (80, "too_high"),
     (None, "sensor_error"), (-3, "sensor_error"), (104, "sensor_error")],
)
def test_classify_soil_moisture(value, expected):
    assert classify(value, (35, 65), METRICS["soil_moisture"]) == expected


def test_nan_from_failed_dht22_read_becomes_missing():
    assert reading(temperature=math.nan).temperature is None


def test_moisture_trend_is_slope_per_hour():
    history = [reading(0, 50), reading(60, 48), reading(120, 46)]
    assert moisture_trend(history) == pytest.approx(-2.0)


def test_moisture_trend_restarts_after_watering():
    history = [reading(0, 40), reading(60, 38), reading(120, 70), reading(180, 69), reading(240, 68)]
    assert moisture_trend(history) == pytest.approx(-1.0)


def test_moisture_trend_needs_enough_history():
    assert moisture_trend([reading(0, 50)]) is None
    assert moisture_trend([reading(0, 50), reading(5, 49)]) is None


def test_hours_until_dry():
    assert hours_until_dry(45, -2.0, 35) == 5.0
    assert hours_until_dry(45, 0.5, 35) is None
    assert hours_until_dry(30, -1.0, 35) == 0.0


@pytest.mark.parametrize(
    ("scenario", "baseline"),
    [("healthy", "low"), ("drying_fast", "medium"), ("critically_dry", "critical"), ("overwatered", "high"),
     ("heat_stress", "high"), ("sensor_fault", "medium"), ("going_on_trip", "low")],
)
def test_scenario_baselines(pothos, scenario, baseline):
    readings = SCENARIOS[scenario].readings()
    report = EnvironmentAgent(pothos).run(readings[-1], readings)
    assert report.source == "rules"
    assert report.baseline_priority == baseline


def test_soil_drying_within_two_hours_is_high(pothos):
    history = [reading(0, 42), reading(60, 39.5), reading(120, 37)]
    report = EnvironmentAgent(pothos).evaluate(history[-1], history)
    assert report.hours_until_dry == pytest.approx(0.8)
    assert report.baseline_priority == "high"
    assert "dry threshold" in report.concerns[0]


def test_sensor_error_is_reported_not_guessed(pothos):
    report = EnvironmentAgent(pothos).evaluate(reading(temperature=None, humidity=None))
    assert report.metrics["temperature"].state == "sensor_error"
    assert any("Temperature sensor" in c for c in report.concerns)


def test_llm_assessment_is_merged_with_rule_metrics(pothos):
    assessment = EnvironmentAssessment(condition="fair", summary="Soil is drying.", concerns=["Drying fast"])
    llm = FakeLLM({EnvironmentAssessment: assessment})
    history = [reading(0, 44), reading(60, 42), reading(120, 40)]

    report = EnvironmentAgent(pothos, llm).run(history[-1], history)

    assert report.source == "llm"
    assert report.summary == "Soil is drying."
    assert report.baseline_priority == "medium"  # stays rule-based
    prompt = llm.prompts[EnvironmentAssessment][0][1].content
    assert "Soil moisture: 40.0 %" in prompt and "-2.00 %/h" in prompt


def test_llm_failure_falls_back_to_rules(pothos):
    llm = FakeLLM({EnvironmentAssessment: TimeoutError("LLM timed out")})
    report = EnvironmentAgent(pothos, llm).run(reading(moisture=20))
    assert report.source == "rules-fallback"
    assert report.baseline_priority == "critical"
