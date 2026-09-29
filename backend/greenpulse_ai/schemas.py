"""Data contracts shared by the agents, the orchestrator and the MQTT layer."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Priority = Literal["low", "medium", "high", "critical"]
PRIORITY_ORDER: tuple[Priority, ...] = ("low", "medium", "high", "critical")

Condition = Literal["good", "fair", "poor", "critical"]
MetricState = Literal["too_low", "low", "optimal", "high", "too_high", "sensor_error"]


def priority_code(priority: Priority) -> int:
    """0 = low ... 3 = critical. The ESP32 uses this number to pick the RGB LED colour."""
    return PRIORITY_ORDER.index(priority)


def max_priority(*priorities: Priority) -> Priority:
    return max(priorities, key=priority_code)


def shift_priority(priority: Priority, steps: int) -> Priority:
    index = min(max(priority_code(priority) + steps, 0), len(PRIORITY_ORDER) - 1)
    return PRIORITY_ORDER[index]


# --------------------------------------------------------------------------- input


class SensorReading(BaseModel):
    """One reading as published by the ESP32 (see mqtt_payloads.Topics.sensors)."""

    device_id: str = "greenpulse-01"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    soil_moisture: float | None = Field(None, description="Calibrated soil moisture, % (0 = dry, 100 = saturated)")
    temperature: float | None = Field(None, description="Air temperature, deg C")
    humidity: float | None = Field(None, description="Relative humidity, %")

    @field_validator("timestamp")
    @classmethod
    def _assume_utc(cls, value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    @field_validator("soil_moisture", "temperature", "humidity")
    @classmethod
    def _nan_is_missing(cls, value: float | None) -> float | None:
        # A failed DHT22 read gives NaN on the ESP32; treat it the same as a missing value.
        return None if value is None or math.isnan(value) else value


# --------------------------------------------------------------------------- agent reports


class MetricStatus(BaseModel):
    value: float | None
    unit: str
    ideal_min: float
    ideal_max: float
    state: MetricState


class EnvironmentReport(BaseModel):
    agent: Literal["environment"] = "environment"
    source: str = Field(description="llm | rules | rules-fallback")
    plant: str
    condition: Condition
    summary: str
    concerns: list[str]
    metrics: dict[str, MetricStatus]
    moisture_trend_per_hour: float | None
    hours_until_dry: float | None
    baseline_priority: Priority = Field(description="Priority from the sensor rules alone; the Plant Doctor's guardrail")


class WeatherReport(BaseModel):
    agent: Literal["weather"] = "weather"
    source: str
    location: str
    summary: str
    temperature_c: float | None = None
    max_temperature_c: float | None = None
    humidity: float | None = None
    rain_expected: bool = False
    heat_alert: bool = False


class Reminder(BaseModel):
    kind: Literal["watering", "fertilising", "repotting", "travel", "other"]
    title: str
    detail: str = ""
    sender: str = ""
    received: datetime | None = None


class NotificationReport(BaseModel):
    agent: Literal["notification"] = "notification"
    source: str
    summary: str
    reminders: list[Reminder] = Field(default_factory=list)


# --------------------------------------------------------------------------- LLM output schemas
# No defaults or constraints here: OpenAI strict structured output requires every field.


class EnvironmentAssessment(BaseModel):
    """The Environment Agent's interpretation of the rule-checked readings."""

    condition: Condition = Field(
        description="good = all readings optimal; fair = minor deviations; "
        "poor = needs attention today; critical = at risk of damage now"
    )
    summary: str = Field(description="At most 2 short plain-language sentences, most important reading first")
    concerns: list[str] = Field(description="Short, specific concerns; empty list if everything is fine")


class CareAdvice(BaseModel):
    """The Plant Doctor's final recommendation."""

    headline: str = Field(description="Action first, at most 8 words, e.g. 'Water within 2 h' or 'No action needed'")
    message: str = Field(description="2-3 friendly sentences for a non-expert explaining what to do and why")
    actions: list[str] = Field(description="1-4 concrete steps, most important first")
    priority: Priority = Field(description="Care urgency; drives the RGB LED on the device")
    reasoning: str = Field(description="One sentence naming which agent findings decided the priority")


# --------------------------------------------------------------------------- final output


class CareResult(BaseModel):
    """Everything one Plant Doctor run produced; mqtt_payloads turns it into MQTT messages."""

    device_id: str
    generated_at: datetime
    trigger: str = Field(description="Why this analysis ran, e.g. 'first reading' or 'moisture changed'")
    reading: SensorReading
    environment: EnvironmentReport
    weather: WeatherReport
    notifications: NotificationReport
    advice: CareAdvice
    doctor_source: str = Field(description="llm | rules | rules-fallback")
    model: str | None
    guardrail_note: str | None = Field(None, description="Set when the sensor guardrail overrode the LLM's priority")
    duration_ms: int

    @property
    def priority(self) -> Priority:
        return self.advice.priority
