"""What the dashboard and the Chat Agent know about each device.

The bridge records every reading, every Plant Doctor result and every pump report here; the dashboard
API and the Chat Agent read from it. It is kept in memory only: after a restart the chart starts
empty and the advice returns with the next analysis. The long-term record is the DynamoDB data log.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .agents.environment import EnvironmentAgent
from .plant_profiles import PlantProfile
from .schemas import CareResult, SensorReading, priority_code
from .watering import WateringDecision

HISTORY = timedelta(hours=24)
# The ESP32 publishes every 10 s (SENSOR_INTERVAL_MS); this long without a reading means it is offline.
OFFLINE_AFTER = timedelta(seconds=90)
MAX_PUMP_EVENTS = 200
SENSOR_KEYS = ("soil_moisture", "temperature", "humidity")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


@dataclass(frozen=True)
class PumpEvent:
    """One pump/state report from the ESP32."""

    at: datetime
    state: str  # on | off | rejected
    source: str  # auto | manual
    seconds: float | None  # planned run time (on) or actual run time (off)
    detail: str  # the reason (on), the result (off) or why the ESP32 refused (rejected)

    def as_dict(self) -> dict:
        return {"at": iso(self.at), "state": self.state, "source": self.source, "seconds": self.seconds, "detail": self.detail}


@dataclass
class _Device:
    readings: deque[SensorReading] = field(default_factory=deque)
    last_seen: datetime | None = None
    result: CareResult | None = None
    watering: WateringDecision | None = None
    pump_events: deque[PumpEvent] = field(default_factory=lambda: deque(maxlen=MAX_PUMP_EVENTS))


class DeviceStore:
    """Thread-safe: the MQTT thread and the analysis worker write while API requests read."""

    def __init__(
        self,
        profile: PlantProfile,
        auto_watering: Callable[[str], bool] = lambda device_id: False,
        clock: Callable[[], datetime] = _utcnow,
        profile_for: Callable[[str], PlantProfile] | None = None,
    ):
        # Which plant each device watches (PlantLibrary.profile_for); without it, `profile` for every device.
        self.profile_for = profile_for or (lambda device_id: profile)
        # Rules only, so the readings on the dashboard are classified fresh every 10 s at no cost,
        # while the (slower, paid) Plant Doctor analysis runs only every few minutes.
        self.environment = EnvironmentAgent(profile)
        self.auto_watering = auto_watering
        self.clock = clock
        self._lock = threading.Lock()
        self._devices: dict[str, _Device] = {}

    # ------------------------------------------------------------------ writes (bridge)

    def record_reading(self, reading: SensorReading) -> None:
        with self._lock:
            device = self._device(reading.device_id)
            device.readings.append(reading)
            device.last_seen = self.clock()
            cutoff = reading.timestamp - HISTORY
            while device.readings and device.readings[0].timestamp < cutoff:
                device.readings.popleft()

    def record_result(self, result: CareResult, watering: WateringDecision | None = None) -> None:
        with self._lock:
            device = self._device(result.device_id)
            device.result = result
            device.watering = watering

    def record_pump_state(self, device_id: str, state: dict, at: datetime | None = None) -> None:
        kind = state.get("state")
        if kind not in ("on", "off", "rejected"):
            return
        seconds = state.get("duration_s") if kind == "on" else state.get("ran_s")
        detail = {"on": state.get("reason"), "off": state.get("result"), "rejected": state.get("detail")}[kind]
        event = PumpEvent(
            at=at or self.clock(),
            state=kind,
            source=str(state.get("source") or "manual"),
            seconds=_number(seconds),
            detail=str(detail or ""),
        )
        with self._lock:
            self._device(device_id).pump_events.append(event)

    # ------------------------------------------------------------------ reads (API, Chat Agent)

    def devices(self) -> list[dict]:
        """Every device seen so far, most recently heard from first."""
        with self._lock:
            seen = [(device_id, d.last_seen) for device_id, d in self._devices.items() if d.last_seen]
        seen.sort(key=lambda item: item[1], reverse=True)
        return [{"device_id": device_id, "online": self._online(last), "last_seen": iso(last)} for device_id, last in seen]

    def readings(self, device_id: str, hours: float = 24) -> list[SensorReading]:
        since = self.clock() - timedelta(hours=hours)
        with self._lock:
            device = self._devices.get(device_id)
            return [r for r in device.readings if r.timestamp >= since] if device else []

    def pump_events(self, device_id: str, hours: float = 24) -> list[PumpEvent]:
        since = self.clock() - timedelta(hours=hours)
        with self._lock:
            device = self._devices.get(device_id)
            return [e for e in device.pump_events if e.at >= since] if device else []

    def snapshot(self, device_id: str) -> dict:
        """Everything the dashboard shows for one device, as JSON-ready data."""
        with self._lock:
            device = self._devices.get(device_id) or _Device()
            readings = list(device.readings)
            last_seen, result, watering = device.last_seen, device.result, device.watering
            events = list(device.pump_events)

        profile = self.profile_for(device_id)
        latest = readings[-1] if readings else None
        environment = self.environment.evaluate(latest, readings, profile) if latest else None
        return {
            "device_id": device_id,
            "plant": profile.as_dict(),
            "online": self._online(last_seen),
            "last_seen": iso(last_seen),
            "reading": latest.model_dump(mode="json") if latest else None,
            "metrics": (
                {key: status.model_dump() for key, status in environment.metrics.items()} if environment else None
            ),
            "moisture_trend_per_hour": environment.moisture_trend_per_hour if environment else None,
            "hours_until_dry": environment.hours_until_dry if environment else None,
            "sensor_priority": environment.baseline_priority if environment else None,
            "analysis": _analysis(result),
            "watering": self._watering(device_id, watering, events),
        }

    def history(self, device_id: str, hours: float = 24, buckets: int = 144) -> dict:
        """Chart data: readings averaged into equal time buckets (null where there was no reading,
        so gaps show as gaps), plus the pump runs in the same window. Times in ms since 1970 (UTC)."""
        now = self.clock()
        start = now - timedelta(hours=hours)
        width = (now - start) / buckets
        sums = [[0.0] * len(SENSOR_KEYS) for _ in range(buckets)]
        counts = [[0] * len(SENSOR_KEYS) for _ in range(buckets)]
        for reading in self.readings(device_id, hours):
            index = min(int((reading.timestamp - start) / width), buckets - 1)
            for k, key in enumerate(SENSOR_KEYS):
                value = getattr(reading, key)
                if value is not None:
                    sums[index][k] += value
                    counts[index][k] += 1

        points = []
        for i in range(buckets):
            point: dict = {"t": _ms(start + width * (i + 0.5))}
            for k, key in enumerate(SENSOR_KEYS):
                point[key] = round(sums[i][k] / counts[i][k], 1) if counts[i][k] else None
            points.append(point)
        waterings = [
            {"t": _ms(e.at), "source": e.source, "seconds": e.seconds}
            for e in self.pump_events(device_id, hours)
            if e.state == "on"
        ]
        return {"device_id": device_id, "hours": hours, "points": points, "waterings": waterings}

    # ------------------------------------------------------------------ helpers

    def _device(self, device_id: str) -> _Device:
        return self._devices.setdefault(device_id, _Device())

    def _online(self, last_seen: datetime | None) -> bool:
        return last_seen is not None and self.clock() - last_seen <= OFFLINE_AFTER

    def _watering(self, device_id: str, decision: WateringDecision | None, events: list[PumpEvent]) -> dict:
        runs = [e for e in events if e.state == "on"]
        last = events[-1] if events else None
        # Running until the ESP32 reports "off", or until the planned time is well over (a lost "off" message).
        running = bool(
            last
            and last.state == "on"
            and self.clock() - last.at <= timedelta(seconds=(last.seconds or 0) + 5)
        )
        return {
            "auto_enabled": self.auto_watering(device_id),
            "pump_running": running,
            "last_watered": iso(runs[-1].at) if runs else None,
            "last_decision": decision.as_payload() if decision else None,
            "events": [e.as_dict() for e in reversed(events[-8:])],
        }


def _analysis(result: CareResult | None) -> dict | None:
    if result is None:
        return None
    advice = result.advice
    return {
        "generated_at": iso(result.generated_at),
        "trigger": result.trigger,
        "priority": advice.priority,
        "priority_code": priority_code(advice.priority),
        "headline": advice.headline,
        "message": advice.message,
        "actions": advice.actions,
        "reasoning": advice.reasoning,
        "source": result.doctor_source,
        "model": result.model,
        "guardrail_note": result.guardrail_note,
        "condition": result.environment.condition,
        "summary": result.environment.summary,
        "concerns": result.environment.concerns,
        "weather": result.weather.model_dump(mode="json", exclude={"agent"}),
        "notifications": result.notifications.model_dump(mode="json", exclude={"agent"}),
    }


def _ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
