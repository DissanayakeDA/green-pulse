from greenpulse_ai.agents import DummyNotificationAgent, DummyWeatherAgent, EnvironmentAgent, PlantDoctorAgent
from greenpulse_ai.agents.plant_doctor import apply_guardrail, rule_based_advice
from greenpulse_ai.dummy_data import SCENARIOS
from greenpulse_ai.schemas import CareAdvice

from conftest import FakeLLM


def reports(pothos, scenario_key):
    scenario = SCENARIOS[scenario_key]
    readings = scenario.readings()
    return (
        EnvironmentAgent(pothos).run(readings[-1], readings),
        DummyWeatherAgent(scenario.weather, "Colombo, LK").run(),
        DummyNotificationAgent(scenario.messages).run(),
    )


def advice(priority="low", headline="No action needed", actions=("Keep going",)):
    return CareAdvice(headline=headline, message="m", actions=list(actions), priority=priority, reasoning="r")


def test_guardrail_allows_raising_priority():
    result, note = apply_guardrail(advice("critical"), baseline="medium")
    assert result.priority == "critical" and note is None


def test_guardrail_allows_lowering_by_one_level():
    result, note = apply_guardrail(advice("high"), baseline="critical")
    assert result.priority == "high" and note is None


def test_guardrail_blocks_lowering_by_more_than_one_level():
    result, note = apply_guardrail(advice("low"), baseline="critical")
    assert result.priority == "high"
    assert "raised to 'high'" in note


def test_llm_advice_passes_through_guardrail(pothos):
    llm = FakeLLM({CareAdvice: advice("low", headline="All good")})
    diagnosis = PlantDoctorAgent(pothos, llm).run(*reports(pothos, "critically_dry"))
    assert diagnosis.source == "llm"
    assert diagnosis.advice.priority == "high"
    assert diagnosis.guardrail_note


def test_llm_output_is_tidied(pothos):
    long = advice("medium", headline="W" * 100, actions=["a", " ", "b", "c", "d", "e"])
    diagnosis = PlantDoctorAgent(pothos, FakeLLM({CareAdvice: long})).run(*reports(pothos, "healthy"))
    assert len(diagnosis.advice.headline) <= 60
    assert diagnosis.advice.actions == ["a", "b", "c", "d"]


def test_doctor_prompt_contains_all_three_reports(pothos):
    llm = FakeLLM({CareAdvice: advice("medium")})
    PlantDoctorAgent(pothos, llm).run(*reports(pothos, "drying_fast"))
    system, human = llm.prompts[CareAdvice][0]
    assert 'baseline priority is "medium"' in system.content
    assert "untrusted data" in system.content
    assert '"hours_until_dry"' in human.content
    assert '"heat_alert": true' in human.content
    assert "Watering reminder: Money plant" in human.content


def test_llm_failure_falls_back_to_rules(pothos):
    diagnosis = PlantDoctorAgent(pothos, FakeLLM({CareAdvice: ConnectionError("no network")})).run(
        *reports(pothos, "critically_dry")
    )
    assert diagnosis.source == "rules-fallback"
    assert diagnosis.advice.priority == "critical"
    assert diagnosis.advice.headline == "Water now"


def test_rules_follow_sensors_over_fixed_watering_schedule(pothos):
    result = rule_based_advice(*reports(pothos, "overwatered"))
    assert result.priority == "high"
    assert "Ignore the scheduled watering reminder" in result.actions[0]


def test_rules_pick_most_urgent_issue_as_headline(pothos):
    assert rule_based_advice(*reports(pothos, "heat_stress")).headline == "Move plant somewhere cooler"


def test_rules_prepare_plant_for_travel(pothos):
    result = rule_based_advice(*reports(pothos, "going_on_trip"))
    assert result.priority == "medium"
    assert result.headline == "Water well before your trip"


def test_rules_flag_sensor_fault(pothos):
    result = rule_based_advice(*reports(pothos, "sensor_fault"))
    assert result.headline == "Check the device sensors"
