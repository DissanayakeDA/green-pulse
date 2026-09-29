import json

import pytest

from greenpulse_ai import Settings, Topics, build_messages, build_pipeline, build_service, parse_sensor_payload
from greenpulse_ai.agents import DummyNotificationAgent, DummyWeatherAgent
from greenpulse_ai.dummy_data import SCENARIOS, simulate_readings
from greenpulse_ai.schemas import CareAdvice, EnvironmentAssessment

from conftest import FakeLLM, reading

SETTINGS = Settings(offline=True, device_id="test-01")


class BrokenWeatherAgent:
    name = "weather"

    def run(self):
        raise ConnectionError("weather API down")


@pytest.mark.parametrize("key", SCENARIOS)
def test_every_scenario_produces_publishable_messages(key):
    scenario = SCENARIOS[key]
    pipeline = build_pipeline(
        SETTINGS, None, DummyWeatherAgent(scenario.weather, "Colombo, LK"), DummyNotificationAgent(scenario.messages)
    )
    readings = scenario.readings("test-01")
    result = pipeline.run(readings[-1], readings)

    messages = dict(build_messages(result, Topics()))
    assert set(messages) == {"greenpulse/test-01/ai/input", "greenpulse/test-01/ai/care", "greenpulse/test-01/priority"}
    assert messages["greenpulse/test-01/priority"]["priority"] == result.priority
    for payload in messages.values():
        json.dumps(payload)  # must be JSON-serialisable


def test_llm_mode_end_to_end():
    llm = FakeLLM(
        {
            EnvironmentAssessment: EnvironmentAssessment(condition="poor", summary="Very dry.", concerns=[]),
            CareAdvice: CareAdvice(
                headline="Water now", message="m", actions=["Water"], priority="critical", reasoning="r"
            ),
        }
    )
    pipeline = build_pipeline(Settings(device_id="test-01"), llm)
    result = pipeline.run(reading(moisture=15))
    assert result.environment.source == "llm"
    assert result.doctor_source == "llm"
    assert result.model == Settings().llm_model
    care = dict(build_messages(result, Topics()))["greenpulse/test-01/ai/care"]
    assert care["priority_code"] == 3 and care["led"] == "red"


def test_failing_external_agent_does_not_block_advice():
    pipeline = build_pipeline(SETTINGS, None, weather_agent=BrokenWeatherAgent())
    result = pipeline.run(reading(moisture=15))
    assert result.weather.source == "unavailable"
    assert result.priority == "critical"


def test_service_throttles_llm_runs():
    service = build_service(SETTINGS, None)
    assert service.handle_reading(reading(0, 50)).trigger == "first reading"
    assert service.handle_reading(reading(1, 49.8)) is None
    assert service.handle_reading(reading(2, 44.0)).trigger == "moisture changed"
    assert service.handle_reading(reading(3, 43.9)) is None
    assert service.handle_reading(reading(8, 43.8)).trigger == "interval elapsed"
    assert service.handle_reading(reading(9, 43.8), force=True).trigger == "forced"


def test_service_reruns_when_sensor_priority_changes():
    service = build_service(SETTINGS, None)
    service.handle_reading(reading(0, humidity=60))
    result = service.handle_reading(reading(1, temperature=None))
    assert result.trigger == "sensor priority changed"


def test_service_keeps_history_per_device():
    service = build_service(SETTINGS, None)
    service.handle_reading(reading(0, 50, device_id="a"))
    assert service.handle_reading(reading(0, 50, device_id="b")).trigger == "first reading"


def test_simulated_stream_runs_through_service():
    service = build_service(Settings(offline=True, analysis_interval_s=3600), None)
    results = [r for r in map(service.handle_reading, simulate_readings(count=48)) if r]
    assert 3 <= len(results) < 48
    assert {"low", "high"} <= {r.priority for r in results}


def test_parse_sensor_payload_from_esp32():
    parsed = parse_sensor_payload(
        b'{"soil_moisture": 41.5, "temperature": 29.1, "humidity": null}', device_id="greenpulse-07"
    )
    assert parsed.device_id == "greenpulse-07"
    assert parsed.humidity is None
    assert parsed.timestamp.tzinfo is not None
