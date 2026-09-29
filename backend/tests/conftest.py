import sys
from datetime import datetime, timedelta, timezone
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


@pytest.fixture
def pothos():
    return get_profile("pothos")
