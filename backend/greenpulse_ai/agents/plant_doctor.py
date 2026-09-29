"""Plant Doctor Agent: combines the Environment, Weather and Notification reports into one
care recommendation and urgency level.

The LLM makes the decision, but a sensor guardrail bounds it: the final priority may be at most
one level below the Environment Agent's rule-based baseline, so a hallucinated "all fine" can
never switch the LED to green while the soil is bone dry. Without an LLM (or if it fails) a
rule-based composer produces the advice instead.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel

from ..plant_profiles import PlantProfile
from ..prompts import PLANT_DOCTOR_PROMPT
from ..schemas import (
    CareAdvice,
    EnvironmentReport,
    NotificationReport,
    Priority,
    WeatherReport,
    max_priority,
    priority_code,
    shift_priority,
)
from .environment import NEAR_DRY_MARGIN, PRIORITY_BY_STATE

log = logging.getLogger(__name__)

MAX_HEADLINE_CHARS = 60
MAX_ACTIONS = 4
WATER_ACTION = "Water slowly until water drains from the bottom of the pot"


@dataclass(frozen=True)
class Diagnosis:
    advice: CareAdvice
    source: str  # llm | rules | rules-fallback
    guardrail_note: str | None = None


class PlantDoctorAgent:
    name = "plant_doctor"

    def __init__(self, profile: PlantProfile, llm: BaseChatModel | None = None):
        self.profile = profile
        self._chain = (PLANT_DOCTOR_PROMPT | llm.with_structured_output(CareAdvice)) if llm else None

    def run(
        self, environment: EnvironmentReport, weather: WeatherReport, notifications: NotificationReport
    ) -> Diagnosis:
        if self._chain is None:
            return Diagnosis(rule_based_advice(environment, weather, notifications), "rules")
        try:
            advice: CareAdvice = self._chain.invoke(
                {
                    "baseline_priority": environment.baseline_priority,
                    "plant_name": self.profile.name,
                    "care_notes": self.profile.care_notes,
                    "environment": environment.model_dump_json(indent=2, exclude={"agent"}),
                    "weather": weather.model_dump_json(indent=2, exclude={"agent"}),
                    "notifications": notifications.model_dump_json(indent=2, exclude={"agent"}),
                }
            )
        except Exception:
            log.exception("Plant Doctor LLM call failed; using rule-based advice")
            return Diagnosis(rule_based_advice(environment, weather, notifications), "rules-fallback")

        advice, note = apply_guardrail(tidy(advice), environment.baseline_priority)
        if note:
            log.warning(note)
        return Diagnosis(advice, "llm", note)


def apply_guardrail(advice: CareAdvice, baseline: Priority) -> tuple[CareAdvice, str | None]:
    """Keep the LLM's priority within one level below the sensor baseline (raising it is always allowed)."""
    floor = shift_priority(baseline, -1)
    if priority_code(advice.priority) >= priority_code(floor):
        return advice, None
    note = (
        f"LLM suggested priority '{advice.priority}'; raised to '{floor}' because the sensor baseline "
        f"is '{baseline}' and the LLM may lower it by at most one level"
    )
    return advice.model_copy(update={"priority": floor}), note


def tidy(advice: CareAdvice) -> CareAdvice:
    headline = advice.headline.strip()
    if len(headline) > MAX_HEADLINE_CHARS:
        headline = headline[: MAX_HEADLINE_CHARS - 3].rstrip() + "..."
    actions = [a.strip() for a in advice.actions if a.strip()][:MAX_ACTIONS]
    return advice.model_copy(update={"headline": headline, "actions": actions})


def rule_based_advice(
    environment: EnvironmentReport, weather: WeatherReport, notifications: NotificationReport
) -> CareAdvice:
    """Deterministic Plant Doctor used in offline mode and whenever the LLM is unavailable."""
    moisture = environment.metrics["soil_moisture"]
    temperature = environment.metrics["temperature"]
    humidity = environment.metrics["humidity"]
    reminder_kinds = {r.kind for r in notifications.reminders}
    soil_is_wet = moisture.state in ("high", "too_high")

    priority = environment.baseline_priority
    headlines: list[tuple[Priority, str]] = []  # the most urgent one becomes the headline
    actions: list[str] = []
    reasons = [f"sensor baseline is {environment.baseline_priority}"]

    if moisture.state == "too_low":
        headlines.append(("critical", "Water now"))
        actions.append(WATER_ACTION)
    elif moisture.state == "low":
        headlines.append(("high", "Water within 2 h"))
        actions.append(WATER_ACTION)
    elif moisture.state == "too_high":
        headlines.append(("high", "Stop watering: soil is waterlogged"))
        actions += ["Empty the saucer and check the drainage holes", "Do not water until the top few cm of soil are dry"]
    elif moisture.state == "high":
        headlines.append(("medium", "Skip watering for now"))
        actions.append("Let the top few cm of soil dry before watering again")
    elif environment.hours_until_dry is not None and environment.hours_until_dry <= 12:
        hours = max(1, round(environment.hours_until_dry))
        headlines.append(("high" if environment.hours_until_dry <= 2 else "medium", f"Water within {hours} h"))
        actions.append(f"Water the plant within the next {hours} h")
    elif moisture.state == "optimal" and moisture.value < moisture.ideal_min + NEAR_DRY_MARGIN:
        headlines.append(("medium", "Water later today"))
        actions.append("Water the plant later today")

    if temperature.state in ("high", "too_high"):
        headlines.append((PRIORITY_BY_STATE["temperature"][temperature.state], "Move plant somewhere cooler"))
        actions.append("Move the plant out of direct sun and away from hot windows")
    elif temperature.state in ("low", "too_low"):
        headlines.append((PRIORITY_BY_STATE["temperature"][temperature.state], "Move plant somewhere warmer"))
        actions.append("Keep the plant away from AC vents and cold drafts")

    if humidity.state in ("low", "too_low"):
        actions.append("Mist the leaves or stand the pot on a tray of wet pebbles")
    elif humidity.state == "too_high":
        actions.append("Improve air circulation around the plant")

    if any(m.state == "sensor_error" for m in environment.metrics.values()):
        headlines.append(("medium", "Check the device sensors"))
        actions.append("Check the sensor wiring on the GreenPulse device and restart it")

    if weather.heat_alert and not soil_is_wet and moisture.state != "sensor_error":
        priority = max_priority(priority, "medium")
        actions.append("Check the soil again this afternoon; hot weather dries it faster")
        reasons.append("a hot day is forecast")

    if "watering" in reminder_kinds and soil_is_wet:
        actions.insert(0, "Ignore the scheduled watering reminder: the soil is still wet")
        reasons.append("the watering reminder conflicts with wet soil")

    if "travel" in reminder_kinds:
        priority = max_priority(priority, "medium")
        headlines.append(("medium", "Water well before your trip"))
        actions.append("Before you leave, water thoroughly and move the plant out of direct sun")
        reasons.append("the user will be away")

    for reminder in notifications.reminders:
        if reminder.kind in ("fertilising", "repotting"):
            actions.append(f"Reminder: {reminder.title}")

    actions = list(dict.fromkeys(actions))[:MAX_ACTIONS] or ["Keep the current care routine"]
    message = environment.summary
    if weather.heat_alert or weather.rain_expected:
        message += f" {weather.summary}"
    if notifications.reminders:
        message += f" {notifications.summary}"

    return CareAdvice(
        headline=max(headlines, key=lambda h: priority_code(h[0]))[1] if headlines else "No action needed",
        message=message,
        actions=actions,
        priority=priority,
        reasoning=f"Rule-based decision: {', '.join(reasons)}.",
    )
