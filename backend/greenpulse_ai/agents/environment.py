"""Environment Agent: turns raw sensor readings into an assessment of the plant's conditions.

Deterministic code does the arithmetic (range checks, moisture trend, time until the soil is dry,
baseline priority); the LLM interprets those facts into a plain-language assessment. Without an
LLM, or when the LLM call fails, the rule-based assessment is returned as-is.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel

from ..plant_profiles import PlantProfile
from ..prompts import ENVIRONMENT_PROMPT
from ..schemas import (
    Condition,
    EnvironmentAssessment,
    EnvironmentReport,
    MetricState,
    MetricStatus,
    Priority,
    SensorReading,
    max_priority,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MetricSpec:
    label: str
    unit: str
    profile_range: str  # attribute name on PlantProfile
    margin: float  # distance outside the ideal range at which "low"/"high" becomes "too_low"/"too_high"
    valid: tuple[float, float]  # physically possible values; anything else is a sensor fault


METRICS: dict[str, MetricSpec] = {
    "soil_moisture": MetricSpec("Soil moisture", "%", "moisture", margin=10, valid=(0, 100)),
    "temperature": MetricSpec("Temperature", "°C", "temperature", margin=4, valid=(-20, 60)),
    "humidity": MetricSpec("Humidity", "%", "humidity", margin=15, valid=(0, 100)),
}

CONCERN_TEXT: dict[str, dict[MetricState, str]] = {
    "soil_moisture": {
        "too_low": "Soil is very dry",
        "low": "Soil is drier than ideal",
        "high": "Soil is wetter than ideal",
        "too_high": "Soil is waterlogged, risking root rot",
    },
    "temperature": {
        "too_low": "Room is too cold for the plant",
        "low": "Room is cooler than ideal",
        "high": "Room is warmer than ideal",
        "too_high": "Room is too hot, risking heat stress",
    },
    "humidity": {
        "too_low": "Air is very dry",
        "low": "Air is drier than ideal",
        "high": "Air is more humid than ideal",
        "too_high": "Air is very humid, risking fungal problems",
    },
}

PRIORITY_BY_STATE: dict[str, dict[MetricState, Priority]] = {
    "soil_moisture": {"too_low": "critical", "low": "high", "high": "medium", "too_high": "high", "sensor_error": "medium"},
    "temperature": {"too_low": "high", "low": "medium", "high": "medium", "too_high": "high", "sensor_error": "medium"},
    "humidity": {"too_low": "medium", "low": "low", "high": "low", "too_high": "medium", "sensor_error": "medium"},
}

CONDITION_BY_PRIORITY: dict[Priority, Condition] = {"low": "good", "medium": "fair", "high": "poor", "critical": "critical"}

TREND_WINDOW_H = 6.0  # only recent readings describe the current drying rate
WATERING_JUMP = 8.0  # a rise of this many points between readings means the plant was watered
NEAR_DRY_MARGIN = 5.0  # "optimal" but within this many points of the dry threshold


def classify(value: float | None, ideal: tuple[float, float], spec: MetricSpec) -> MetricState:
    if value is None or not spec.valid[0] <= value <= spec.valid[1]:
        return "sensor_error"
    low, high = ideal
    if value < low - spec.margin:
        return "too_low"
    if value < low:
        return "low"
    if value > high + spec.margin:
        return "too_high"
    if value > high:
        return "high"
    return "optimal"


def moisture_trend(history: Sequence[SensorReading]) -> float | None:
    """Soil moisture change in %/hour since the last watering (least-squares slope), or None."""
    valid = METRICS["soil_moisture"].valid
    points = [
        (r.timestamp, r.soil_moisture)
        for r in history
        if r.soil_moisture is not None and valid[0] <= r.soil_moisture <= valid[1]
    ]
    if len(points) < 2:
        return None
    latest = points[-1][0]
    points = [p for p in points if (latest - p[0]).total_seconds() <= TREND_WINDOW_H * 3600]
    for i in range(len(points) - 1, 0, -1):
        if points[i][1] - points[i - 1][1] > WATERING_JUMP:
            points = points[i:]
            break
    if len(points) < 2 or (points[-1][0] - points[0][0]).total_seconds() < 15 * 60:
        return None

    xs = [(t - points[0][0]).total_seconds() / 3600 for t, _ in points]
    ys = [m for _, m in points]
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    variance = sum((x - mean_x) ** 2 for x in xs)
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    return round(covariance / variance, 2)


def hours_until_dry(moisture: float | None, trend: float | None, dry_threshold: float) -> float | None:
    if moisture is None or trend is None or trend >= -0.05:
        return None
    if moisture <= dry_threshold:
        return 0.0
    return round(min((moisture - dry_threshold) / -trend, 168.0), 1)


class EnvironmentAgent:
    name = "environment"

    def __init__(self, profile: PlantProfile, llm: BaseChatModel | None = None):
        self.profile = profile
        self._chain = (ENVIRONMENT_PROMPT | llm.with_structured_output(EnvironmentAssessment)) if llm else None

    def evaluate(self, reading: SensorReading, history: Sequence[SensorReading] = ()) -> EnvironmentReport:
        """Rule-based assessment only. Cheap, so the service also uses it to decide when to re-run the LLMs."""
        series = list(history) if history and history[-1] is reading else [*history, reading]

        metrics: dict[str, MetricStatus] = {}
        for key, spec in METRICS.items():
            ideal = getattr(self.profile, spec.profile_range)
            value = getattr(reading, key)
            metrics[key] = MetricStatus(
                value=value, unit=spec.unit, ideal_min=ideal[0], ideal_max=ideal[1], state=classify(value, ideal, spec)
            )

        moisture = metrics["soil_moisture"]
        trend = moisture_trend(series) if moisture.state != "sensor_error" else None
        dry_in = hours_until_dry(moisture.value, trend, moisture.ideal_min)

        concerns: list[str] = []
        priorities: list[Priority] = ["low"]
        for key, status in metrics.items():
            if status.state == "optimal":
                continue
            priorities.append(PRIORITY_BY_STATE[key][status.state])
            spec = METRICS[key]
            if status.state == "sensor_error":
                got = "" if status.value is None else f" (got {status.value:g}{spec.unit})"
                concerns.append(f"{spec.label} sensor returned no valid reading{got}")
            else:
                concerns.append(
                    f"{CONCERN_TEXT[key][status.state]} ({status.value:.1f}{spec.unit}, "
                    f"ideal {status.ideal_min:g}-{status.ideal_max:g}{spec.unit})"
                )

        if moisture.state == "optimal":
            if dry_in is not None and dry_in <= 12:
                priorities.append("high" if dry_in <= 2 else "medium")
                concerns.insert(
                    0,
                    f"Soil is drying at {-trend:.1f} %/h and will reach the dry threshold "
                    f"({moisture.ideal_min:g}%) in about {dry_in:g} h",
                )
            elif moisture.value < moisture.ideal_min + NEAR_DRY_MARGIN:
                priorities.append("medium")
                concerns.insert(
                    0, f"Soil is close to the dry threshold ({moisture.value:.1f}%, dry below {moisture.ideal_min:g}%)"
                )

        baseline = max_priority(*priorities)
        condition = CONDITION_BY_PRIORITY[baseline]
        if condition == "good" and concerns:
            condition = "fair"

        return EnvironmentReport(
            source="rules",
            plant=self.profile.name,
            condition=condition,
            summary=self._rule_summary(metrics, concerns),
            concerns=concerns,
            metrics=metrics,
            moisture_trend_per_hour=trend,
            hours_until_dry=dry_in,
            baseline_priority=baseline,
        )

    def run(self, reading: SensorReading, history: Sequence[SensorReading] = ()) -> EnvironmentReport:
        report = self.evaluate(reading, history)
        if self._chain is None:
            return report
        try:
            assessment: EnvironmentAssessment = self._chain.invoke(self._prompt_inputs(reading, report))
        except Exception:
            log.exception("Environment Agent LLM call failed; using the rule-based assessment")
            return report.model_copy(update={"source": "rules-fallback"})
        return report.model_copy(update={"source": "llm", **assessment.model_dump()})

    def _prompt_inputs(self, reading: SensorReading, report: EnvironmentReport) -> dict[str, str]:
        rows = []
        for key, status in report.metrics.items():
            spec = METRICS[key]
            value = "no valid value" if status.value is None else f"{status.value:.1f} {spec.unit}"
            rows.append(
                f"- {spec.label}: {value} (ideal {status.ideal_min:g}-{status.ideal_max:g} {spec.unit}) -> {status.state}"
            )

        if report.moisture_trend_per_hour is None:
            trend = "not enough recent history yet"
        else:
            trend = f"{report.moisture_trend_per_hour:+.2f} %/h"
            if report.hours_until_dry is not None:
                trend += f"; reaches the dry threshold in about {report.hours_until_dry:g} h"

        return {
            "plant_name": self.profile.name,
            "care_notes": self.profile.care_notes,
            "timestamp": reading.timestamp.isoformat(timespec="seconds"),
            "metrics_table": "\n".join(rows),
            "trend": trend,
            "rule_concerns": "; ".join(report.concerns) or "none",
        }

    @staticmethod
    def _rule_summary(metrics: dict[str, MetricStatus], concerns: list[str]) -> str:
        parts = []
        for key, status in metrics.items():
            if status.value is not None:
                parts.append(f"{METRICS[key].label.lower()} {status.value:.1f}{status.unit}")
        if not concerns:
            return f"All readings are in the ideal range ({', '.join(parts)})."
        return ". ".join(concerns[:2]) + "."
