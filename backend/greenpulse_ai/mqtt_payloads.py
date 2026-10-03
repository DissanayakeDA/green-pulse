"""MQTT contract between the ESP32, this backend and the Node-RED dashboard.

The topic names are a proposal for the Cloud MQTT component (Karunarathna K M D K) to finalise.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .schemas import CareResult, SensorReading, priority_code
from .watering import WateringDecision

LED_COLOURS = {"low": "green", "medium": "yellow", "high": "orange", "critical": "red"}


@dataclass(frozen=True)
class Topics:
    prefix: str = "greenpulse"

    def sensors(self, device_id: str) -> str:  # ESP32 -> backend, Node-RED
        return f"{self.prefix}/{device_id}/sensors"

    def status(self, device_id: str) -> str:  # ESP32 -> Node-RED: online/offline (retained, last will)
        return f"{self.prefix}/{device_id}/status"

    def ai_input(self, device_id: str) -> str:  # backend -> Node-RED: what the Plant Doctor was given
        return f"{self.prefix}/{device_id}/ai/input"

    def care(self, device_id: str) -> str:  # backend -> Node-RED: the Plant Doctor's advice (retained)
        return f"{self.prefix}/{device_id}/ai/care"

    def priority(self, device_id: str) -> str:  # backend -> ESP32: RGB LED only (retained)
        return f"{self.prefix}/{device_id}/priority"

    # Never retain pump commands: the ESP32 would re-run a stale command every time it reconnects.
    def pump_command(self, device_id: str) -> str:  # backend (auto) or Node-RED (manual) -> ESP32
        return f"{self.prefix}/{device_id}/pump/command"

    def pump_state(self, device_id: str) -> str:  # ESP32 -> backend, Node-RED: on / off / rejected
        return f"{self.prefix}/{device_id}/pump/state"

    def pump_auto(self, device_id: str) -> str:  # Node-RED switch -> backend: auto-watering on/off (retained)
        return f"{self.prefix}/{device_id}/pump/auto"

    def retained(self, device_id: str) -> set[str]:
        """Backend topics published with the retain flag, so late subscribers get the current value."""
        return {self.care(device_id), self.priority(device_id)}


def parse_sensor_payload(payload: bytes | str, device_id: str | None = None) -> SensorReading:
    """Parse the ESP32 JSON. device_id (e.g. taken from the topic) fills in when the payload lacks one."""
    data = json.loads(payload)
    if device_id:
        data.setdefault("device_id", device_id)
    return SensorReading.model_validate(data)


def build_messages(
    result: CareResult, topics: Topics, watering: WateringDecision | None = None
) -> list[tuple[str, dict]]:
    """The (topic, JSON payload) pairs to publish after one Plant Doctor run. The pump command itself is
    published separately (WateringDecision.command) and only when the decision is to water."""
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
    if watering is not None:
        care["watering"] = watering.as_payload()
    device ={"priority": priority, "priority_code": priority_code(priority), "led": LED_COLOURS[priority]}

    return [
        (topics.ai_input(device_id), ai_input),
        (topics.care(device_id), care),
        (topics.priority(device_id), device),
    ]
