"""MQTT contract between the ESP32, this backend and the Node-RED dashboard.

The topic names are a proposal for the Cloud MQTT component (Karunarathna K M D K) to finalise.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .schemas import CareResult, SensorReading, priority_code

LED_COLOURS = {"low": "green", "medium": "yellow", "high": "orange", "critical": "red"}


@dataclass(frozen=True)
class Topics:
    prefix: str = "greenpulse"

    def sensors(self, device_id: str) -> str:  # ESP32 -> backend
        return f"{self.prefix}/{device_id}/sensors"

    def ai_input(self, device_id: str) -> str:  # backend -> Node-RED: what the Plant Doctor was given
        return f"{self.prefix}/{device_id}/ai/input"

    def care(self, device_id: str) -> str:  # backend -> Node-RED: the Plant Doctor's advice
        return f"{self.prefix}/{device_id}/ai/care"

    def priority(self, device_id: str) -> str:  # backend -> ESP32: RGB LED only (publish retained)
        return f"{self.prefix}/{device_id}/priority"


def parse_sensor_payload(payload: bytes | str, device_id: str | None = None) -> SensorReading:
    """Parse the ESP32 JSON. device_id (e.g. taken from the topic) fills in when the payload lacks one."""
    data = json.loads(payload)
    if device_id:
        data.setdefault("device_id", device_id)
    return SensorReading.model_validate(data)


def build_messages(result: CareResult, topics: Topics) -> list[tuple[str, dict]]:
    """The (topic, JSON payload) pairs to publish after one Plant Doctor run."""
    device_id = result.device_id
    timestamp = result.generated_at.isoformat(timespec="seconds")
    priority = result.advice.priority

    ai_input = {
        "device_id": device_id,
        "timestamp": timestamp,
        "trigger": result.trigger,
        "reading": result.reading.model_dump(mode="json"),
        "environment": result.environment.model_dump(mode="json"),
        "weather": result.weather.model_dump(mode="json"),
        "notifications": result.notifications.model_dump(mode="json"),
    }
    care = {
        "device_id": device_id,
        "timestamp": timestamp,
        "priority": priority,
        "priority_code": priority_code(priority),
        "led": LED_COLOURS[priority],
        "headline": result.advice.headline,
        "message": result.advice.message,
        "actions": result.advice.actions,
        "reasoning": result.advice.reasoning,
        "source": result.doctor_source,
        "model": result.model,
        "guardrail_note": result.guardrail_note,
        "trigger": result.trigger,
        "duration_ms": result.duration_ms,
    }
    device = {"priority": priority, "priority_code": priority_code(priority), "led": LED_COLOURS[priority]}

    return [
        (topics.ai_input(device_id), ai_input),
        (topics.care(device_id), care),
        (topics.priority(device_id), device),
    ]
