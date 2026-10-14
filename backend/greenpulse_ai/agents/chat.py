"""Chat Agent: answers the owner's questions about the plant, such as "How is my plant doing?" or
"When was it last watered?", from the live device data.

The LLM decides which read-only tools to call (current status, Plant Doctor report, sensor history,
watering log) and answers from what they return. None of the tools acts on the device: watering
stays with the dashboard button and the auto-watering safety gates. Without an LLM, or when the LLM
fails, a rule-based answer summarises the current status instead.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from ..prompts import CHAT_PROMPT

if TYPE_CHECKING:
    from ..device_state import DeviceStore, PumpEvent

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 4  # LLM calls per question; a normal answer needs 2 (look up, then answer)
MAX_HISTORY_TURNS = 10  # earlier chat messages sent along for follow-up questions
SENSOR_LABELS = {"soil_moisture": "soil moisture", "temperature": "temperature", "humidity": "humidity"}
STATE_WORDS = {
    "too_low": "far too low",
    "low": "a bit low",
    "optimal": "ideal",
    "high": "a bit high",
    "too_high": "far too high",
    "sensor_error": "sensor not responding",
}


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatAnswer(BaseModel):
    answer: str
    source: str = Field(description="llm | rules | rules-fallback")
    tools: list[str] = Field(description="The tools the agent called, in order")
    model: str | None = None


class ChatAgent:
    name = "chat"

    def __init__(
        self,
        store: DeviceStore,
        llm: BaseChatModel | None = None,
        model: str | None = None,
        location: str = "",
        timezone_name: str = "UTC",
    ):
        self.store = store
        self.llm = llm
        self.model = model if llm else None
        self.location = location
        try:
            self.tz = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            log.warning("Unknown TIMEZONE %r; chat answers use UTC", timezone_name)
            self.tz = timezone.utc

    def ask(self, device_id: str, question: str, history: Sequence[ChatTurn] = ()) -> ChatAnswer:
        if self.llm is None:
            return ChatAnswer(answer=self._fallback(device_id, question), source="rules", tools=[])

        tools = {tool.name: tool for tool in self._tools(device_id)}
        llm = self.llm.bind_tools(list(tools.values()))
        plant = self.store.profile_for(device_id)
        messages = CHAT_PROMPT.invoke(
            {
                "plant_name": plant.name,
                "moisture": f"{plant.moisture[0]:g}-{plant.moisture[1]:g} %",
                "temperature": f"{plant.temperature[0]:g}-{plant.temperature[1]:g} °C",
                "humidity": f"{plant.humidity[0]:g}-{plant.humidity[1]:g} %",
                "care_notes": plant.care_notes or "none given",
                "location": self.location or "an unknown location",
                "device_id": device_id,
                "now": self.store.clock().astimezone(self.tz).strftime("%A %d %B %Y, %H:%M"),
                "messages": [*_history_messages(history), HumanMessage(question)],
            }
        ).to_messages()

        used: list[str] = []
        try:
            for _ in range(MAX_TOOL_ROUNDS):
                reply = llm.invoke(messages)
                messages.append(reply)
                if not reply.tool_calls:
                    answer = reply.text.strip()
                    if not answer:
                        raise ValueError("the LLM returned an empty answer")
                    return ChatAnswer(answer=answer, source="llm", tools=used, model=self.model)
                for call in reply.tool_calls:
                    used.append(call["name"])
                    messages.append(ToolMessage(_run_tool(tools, call), tool_call_id=call["id"]))
            raise RuntimeError(f"no answer after {MAX_TOOL_ROUNDS} LLM calls")
        except Exception:
            log.exception("Chat Agent LLM call failed; using the rule-based answer")
            return ChatAnswer(answer=self._fallback(device_id, question), source="rules-fallback", tools=used)

    # ------------------------------------------------------------------ tools

    def _tools(self, device_id: str) -> list[BaseTool]:
        def current_status() -> dict:
            """The latest sensor readings compared with the plant's ideal ranges, the soil-drying trend,
            and whether the device is online."""
            return self.current_status(device_id)

        def plant_doctor_report() -> dict:
            """The Plant Doctor's latest analysis: care priority, advice, actions and reasoning, plus the
            weather forecast and email reminders it took into account."""
            return self.plant_doctor_report(device_id)

        def sensor_history(hours: float = 24) -> dict:
            """How soil moisture, temperature and humidity changed over the last `hours` hours (0.5 to 24):
            first, last, lowest and highest values with their times, and soil moisture over time."""
            return self.sensor_history(device_id, hours)

        def watering_log(hours: float = 24) -> dict:
            """Pump runs (manual and automatic), refusals by the device, the auto-watering setting and why
            the last automatic decision did or did not water, over the last `hours` hours (0.5 to 24)."""
            return self.watering_log(device_id, hours)

        return [
            StructuredTool.from_function(f) for f in (current_status, plant_doctor_report, sensor_history, watering_log)
        ]

    def current_status(self, device_id: str) -> dict:
        snapshot = self.store.snapshot(device_id)
        if snapshot["reading"] is None:
            return {"error": f"No reading from {device_id} yet. The device may be off or not connected."}
        trend = snapshot["moisture_trend_per_hour"]
        return {
            "device_online": snapshot["online"],
            "last_reading": self._when(snapshot["reading"]["timestamp"]),
            "readings": {
                key: {
                    "value": m["value"],
                    "unit": m["unit"],
                    "ideal_range": f"{m['ideal_min']:g}-{m['ideal_max']:g}",
                    "state": m["state"],
                }
                for key, m in snapshot["metrics"].items()
            },
            "soil_moisture_trend": None if trend is None else f"{trend:+.1f} % per hour",
            "hours_until_soil_is_dry": snapshot["hours_until_dry"],
            "priority_from_sensors": snapshot["sensor_priority"],
        }

    def plant_doctor_report(self, device_id: str) -> dict:
        snapshot = self.store.snapshot(device_id)
        analysis = snapshot["analysis"]
        if analysis is None:
            return {"error": "The Plant Doctor has not analysed a reading from this device yet."}
        notifications = analysis["notifications"]
        return {
            "analysed": self._when(analysis["generated_at"]),
            "priority": analysis["priority"],
            "headline": analysis["headline"],
            "message": analysis["message"],
            "actions": analysis["actions"],
            "reasoning": analysis["reasoning"],
            "plant_condition": analysis["condition"],
            "concerns": analysis["concerns"],
            "weather": analysis["weather"],
            "email": notifications["summary"],
            "email_reminders": [
                {"kind": r["kind"], "title": r["title"], "detail": r["detail"]} for r in notifications["reminders"]
            ],
            "auto_watering_decision": snapshot["watering"]["last_decision"],
        }

    def sensor_history(self, device_id: str, hours: float = 24) -> dict:
        hours = min(max(float(hours), 0.5), 24.0)
        readings = self.store.readings(device_id, hours)
        if not readings:
            return {"error": f"No readings in the last {hours:g} h."}

        summary: dict = {
            "period": f"last {hours:g} h",
            "readings": len(readings),
            "from": self._when(readings[0].timestamp),
            "to": self._when(readings[-1].timestamp),
        }
        for key in SENSOR_LABELS:
            points = [(r.timestamp, getattr(r, key)) for r in readings if getattr(r, key) is not None]
            if not points:
                summary[key] = "no valid values"
                continue
            low = min(points, key=lambda p: p[1])
            high = max(points, key=lambda p: p[1])
            summary[key] = {
                "first": points[0][1],
                "last": points[-1][1],
                "lowest": low[1],
                "lowest_at": self._when(low[0]),
                "highest": high[1],
                "highest_at": self._when(high[0]),
                "average": round(sum(v for _, v in points) / len(points), 1),
            }

        chart = self.store.history(device_id, hours, buckets=max(4, min(24, round(hours * 2))))
        summary["soil_moisture_over_time"] = [
            {"time": self._clock(p["t"]), "value": p["soil_moisture"]} for p in chart["points"] if p["soil_moisture"] is not None
        ]
        summary["waterings"] = len(chart["waterings"])
        return summary

    def watering_log(self, device_id: str, hours: float = 24) -> dict:
        hours = min(max(float(hours), 0.5), 24.0)
        watering = self.store.snapshot(device_id)["watering"]
        events = self.store.pump_events(device_id, hours)
        return {
            "auto_watering": "on" if watering["auto_enabled"] else "off",
            "pump_running_now": watering["pump_running"],
            "last_watered": self._when(watering["last_watered"]) or "no watering recorded since the backend started",
            "events_newest_first": [{"time": self._when(e.at), "event": _describe(e)} for e in reversed(events[-15:])],
            "last_auto_watering_decision": watering["last_decision"],
        }

    # ------------------------------------------------------------------ helpers

    def _fallback(self, device_id: str, question: str) -> str:
        return rule_based_answer(self.store.snapshot(device_id), question, self._when)

    def _when(self, value: str | datetime | None) -> str | None:
        """'14:05 (35 min ago)' in local time, with the day when it is not today."""
        if value is None:
            return None
        moment = datetime.fromisoformat(value) if isinstance(value, str) else value
        now = self.store.clock()
        local, today = moment.astimezone(self.tz), now.astimezone(self.tz).date()
        if local.date() == today:
            day = ""
        elif local.date() == today - timedelta(days=1):
            day = "yesterday "
        else:
            day = local.strftime("%a %d %b ")
        return f"{day}{local:%H:%M} ({_ago(now - moment)})"

    def _clock(self, ms: int) -> str:
        return datetime.fromtimestamp(ms / 1000, self.tz).strftime("%H:%M")


def rule_based_answer(snapshot: dict, question: str, when) -> str:
    """The answer without an LLM: the Plant Doctor's last advice and the current readings, plus the
    watering or weather details when the question is about those."""
    plant = snapshot["plant"]["name"]
    if snapshot["reading"] is None:
        return (
            f"I have no readings from {snapshot['device_id']} yet, so I can't tell how your {plant} is doing. "
            "Check that the GreenPulse device is switched on and connected."
        )

    readings = []
    for key, label in SENSOR_LABELS.items():
        m = snapshot["metrics"][key]
        value = "unknown" if m["value"] is None else f"{m['value']:.0f}{'' if m['unit'] == '%' else ' '}{m['unit']}"
        readings.append(f"{label} {value} ({STATE_WORDS[m['state']]})")

    sentences = []
    analysis = snapshot["analysis"]
    if analysis:
        sentences.append(f"{analysis['headline'].rstrip('.')}.")
    sentences.append(f"Right now your {plant} has {', '.join(readings)}.")
    if analysis and analysis["priority"] != "low":  # when all is well, the message only repeats the readings
        sentences.append(analysis["message"])
    if not snapshot["online"]:
        sentences.append(f"The device is offline; the last reading came in at {when(snapshot['last_seen'])}.")

    question = question.lower()
    watering = snapshot["watering"]
    if any(word in question for word in ("water", "pump", "thirst", "dry")):
        last = when(watering["last_watered"])
        sentences.append(f"Last watering: {last}." if last else "No watering has been recorded since the backend started.")
        sentences.append(f"Auto-watering is {'on' if watering['auto_enabled'] else 'off'}.")
    if analysis and any(word in question for word in ("weather", "rain", "hot", "heat", "sun", "forecast")):
        sentences.append(analysis["weather"]["summary"])
    return " ".join(sentences)


def _history_messages(history: Sequence[ChatTurn]) -> list[BaseMessage]:
    turns = list(history)[-MAX_HISTORY_TURNS:]
    return [HumanMessage(t.content) if t.role == "user" else AIMessage(t.content) for t in turns]


def _run_tool(tools: dict[str, BaseTool], call: dict) -> str:
    tool = tools.get(call["name"])
    if tool is None:
        result: dict = {"error": f"There is no tool called {call['name']!r}."}
    else:
        try:
            result = tool.invoke(call.get("args") or {})
        except Exception as exc:  # e.g. arguments the model made up
            result = {"error": str(exc)}
    return json.dumps(result, ensure_ascii=False, default=str)


def _describe(event: PumpEvent) -> str:
    seconds = "" if event.seconds is None else f" {event.seconds:g} s"
    if event.state == "on":
        return f"pump started for{seconds} ({event.source})" + (f": {event.detail}" if event.detail else "")
    if event.state == "off":
        return f"pump stopped after{seconds} ({event.source}, {event.detail or 'done'})"
    return f"device refused to pump ({event.source}): {event.detail}"


def _ago(age: timedelta) -> str:
    seconds = age.total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60:.0f} min ago"
    if seconds < 86400:
        hours = seconds / 3600
        return f"{hours:.1f} h ago" if hours < 10 else f"{hours:.0f} h ago"
    return f"{seconds // 86400:.0f} days ago"
