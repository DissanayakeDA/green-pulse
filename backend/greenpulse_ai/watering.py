"""Auto-watering: the Plant Doctor's one physical action. After each analysis, decide whether to run the pump.

The LLM cannot switch the pump on by itself. The pump runs only when all of these hold:

- auto-watering is enabled (AUTO_WATERING in .env, or the Node-RED switch)
- the soil-moisture sensor itself reads below the plant's ideal range
- the Plant Doctor rates the situation high or critical
- the last watering (auto or manual) was at least `cooldown_s` ago, so the last pulse has soaked in
- fewer than `max_per_day` pulses ran in the last 24 h (a leak or a dead sensor cannot empty the tank)

Watering is a short pulse followed by a soak: the sensor reacts slowly, so one long run would overshoot.
The ESP32 also enforces its own hard limits (maximum run time, rest time, wet-soil cut-off).
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from .config import Settings
from .schemas import CareResult, priority_code

DRY_STATES = {"low", "too_low"}
MIN_PRIORITY = "high"
DAY = timedelta(hours=24)


@dataclass(frozen=True)
class WateringDecision:
    water: bool
    reason: str
    auto_enabled: bool
    duration_s: float = 0.0

    def as_payload(self) -> dict:
        """Added to the ai/care message so the dashboard shows why the pump did or did not run."""
        return {
            "auto_enabled": self.auto_enabled,
            "decision": "water" if self.water else "skip",
            "duration_s": self.duration_s,
            "reason": self.reason,
        }

    def command(self) -> dict:
        """The pump/command payload for the ESP32."""
        return {"action": "on", "duration_s": self.duration_s, "source": "auto", "reason": self.reason}


class WateringPolicy:
    """Thread-safe: the MQTT thread records pump events and switch changes while the worker decides."""

    def __init__(self, enabled: bool = False, pulse_s: float = 5.0, cooldown_s: int = 1800, max_per_day: int = 6):
        self.default_enabled = enabled
        self.pulse_s = pulse_s
        self.cooldown = timedelta(seconds=cooldown_s)
        self.max_per_day = max_per_day
        self._lock = threading.Lock()
        self._enabled: dict[str, bool] = {}
        self._runs: dict[str, deque[tuple[datetime, str]]] = defaultdict(deque)  # (started, source)

    @classmethod
    def from_settings(cls, settings: Settings) -> WateringPolicy:
        return cls(settings.auto_watering, settings.water_pulse_s, settings.water_cooldown_s, settings.water_max_per_day)

    def set_enabled(self, device_id: str, enabled: bool) -> None:
        with self._lock:
            self._enabled[device_id] = enabled

    def is_enabled(self, device_id: str) -> bool:
        with self._lock:
            return self._enabled.get(device_id, self.default_enabled)

    def record_pump_state(self, device_id: str, state: dict, now: datetime) -> None:
        """Feed every pump/state message from the ESP32.

        Manual runs (the dashboard button) start the cooldown too. An auto run is already recorded when it
        is decided, so a lost state message cannot cause a double watering; if the ESP32 rejects it, the
        record is removed again.
        """
        source = state.get("source")
        with self._lock:
            runs = self._runs[device_id]
            if state.get("state") == "on" and source != "auto":
                runs.append((now, source or "manual"))
            elif state.get("state") == "rejected" and source == "auto" and runs and runs[-1][1] == "auto":
                runs.pop()

    def decide(self, result: CareResult, now: datetime) -> WateringDecision:
        device_id = result.device_id
        with self._lock:
            enabled = self._enabled.get(device_id, self.default_enabled)
            if not enabled:
                return WateringDecision(False, "Auto-watering is off", enabled)

            moisture = result.environment.metrics["soil_moisture"]
            if moisture.state == "sensor_error":
                return WateringDecision(False, "Soil sensor has no valid reading; not watering blind", enabled)
            if moisture.state not in DRY_STATES:
                return WateringDecision(False, f"Soil moisture is {moisture.state.replace('_', ' ')}", enabled)
            if priority_code(result.priority) < priority_code(MIN_PRIORITY):
                return WateringDecision(False, f"Plant Doctor priority is {result.priority}, below {MIN_PRIORITY}", enabled)

            runs = self._runs[device_id]
            while runs and now - runs[0][0] >= DAY:
                runs.popleft()
            if runs and now - runs[-1][0] < self.cooldown:
                wait_s = (self.cooldown - (now - runs[-1][0])).total_seconds()
                wait = f"{wait_s:.0f} s" if wait_s < 90 else f"{wait_s / 60:.0f} min"
                return WateringDecision(False, f"Watered recently; letting it soak for another {wait}", enabled)
            if len(runs) >= self.max_per_day:
                return WateringDecision(
                    False,
                    f"Already watered {len(runs)} times in 24 h; check the tank, tubing and soil sensor",
                    enabled,
                )

            runs.append((now, "auto"))
            return WateringDecision(
                True,
                f"Soil at {moisture.value:.0f}% is below {moisture.ideal_min:g}% and the Plant Doctor rates it "
                f"{result.priority}",
                enabled,
                self.pulse_s,
            )
