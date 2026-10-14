"""Demo mode: a simulated ESP32 instead of the MQTT broker, so the dashboard and the chat can be tried
without the hardware.

    python -m greenpulse_ai.bridge --demo               # soil starts at 40 %
    python -m greenpulse_ai.bridge --demo 25 --offline  # dry soil, rule-based agents only

SimulatedEsp32 stands in for the paho MQTT client. The bridge "publishes" to it, and it feeds readings
and pump reports back through the bridge's normal message handler, so the same code runs as in the
live setup. The soil dries slowly, and the pretend pump wets it within the firmware's limits.
"""

from __future__ import annotations

import json
import math
import random
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING

from .mqtt_payloads import Topics
from .schemas import SensorReading

if TYPE_CHECKING:
    from .device_state import DeviceStore

# The firmware's defaults (config.example.h).
PUMP_MAX_RUN_S = 15
PUMP_MIN_REST_S = 60
PUMP_WET_CUTOFF = 75.0

SOIL_PER_PUMP_SECOND = 2.5  # moisture points one second of pumping adds
WATERED_TO = 68.0  # backfill: soil moisture right after the simulated owner watered by hand
DRY_AT = 31.0  # backfill: how dry the soil was when they did


def _drying_rate(temperature: float) -> float:
    """Moisture points lost per hour; the soil dries faster when the room is warm."""
    return max(0.6, 1.6 + 0.25 * (temperature - 28))


class SimulatedEsp32:
    def __init__(
        self,
        device_id: str = "greenpulse-01",
        prefix: str = "greenpulse",
        soil: float = 40.0,
        interval_s: float = 10.0,
        seed: int = 7,
    ):
        self.device_id = device_id
        self.topics = Topics(prefix)
        self.interval_s = interval_s
        self.soil = soil
        self.rng = random.Random(seed)
        # Set by the Bridge, as on a paho client.
        self.on_connect = self.on_disconnect = self.on_message = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._last_tick = time.monotonic()
        self._pump_running = False
        self._pump_stopped = -math.inf

    # ------------------------------------------------------------------ the paho client methods the Bridge uses

    def connect_async(self, host: str, port: int, keepalive: int = 60) -> None:
        pass

    def loop_forever(self, retry_first_connection: bool = False) -> None:
        while not self._stop.is_set():
            self._deliver(self.topics.sensors(self.device_id), self.reading())
            self._stop.wait(self.interval_s)

    def disconnect(self) -> None:
        self._stop.set()

    def publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False) -> None:
        if topic == self.topics.pump_command(self.device_id):
            self.command(json.loads(payload))
        elif topic == self.topics.pump_auto(self.device_id):
            self._deliver(topic, payload)  # a broker would pass the switch back to the subscribed bridge
        # ai/input, ai/care and priority go to Node-RED and the RGB LED, which the demo doesn't have.

    # ------------------------------------------------------------------ the simulated device

    def reading(self) -> dict:
        temperature, humidity = self._climate(datetime.now(timezone.utc))
        with self._lock:
            now = time.monotonic()
            self.soil = max(5.0, self.soil - _drying_rate(temperature) * (now - self._last_tick) / 3600)
            self._last_tick = now
            soil = self.soil
        return {"soil_moisture": round(soil, 1), "temperature": round(temperature, 1), "humidity": round(humidity, 1)}

    def command(self, command: dict) -> None:
        """A pump/command, handled like the firmware does: refused while running or resting, or when the
        soil is already wet; otherwise the pump runs and reports "on", then "off"."""
        if command.get("action") != "on":
            return  # "off": the simulated pump always finishes within seconds anyway
        source = str(command.get("source") or "manual")
        seconds = min(float(command.get("duration_s") or 0), PUMP_MAX_RUN_S)
        with self._lock:
            rest_left = PUMP_MIN_REST_S - (time.monotonic() - self._pump_stopped)
            if self._pump_running:
                refused = "pump is already running"
            elif not seconds > 0:
                refused = "duration_s must be above 0"
            elif rest_left > 0:
                refused = f"pump is resting, {rest_left:.0f} s left"
            elif self.soil >= PUMP_WET_CUTOFF:
                refused = f"soil is already wet ({self.soil:.0f}%)"
            else:
                refused = None
                self._pump_running = True

        topic = self.topics.pump_state(self.device_id)
        if refused:
            self._deliver(topic, {"state": "rejected", "source": source, "detail": refused})
            return
        self._deliver(topic, {"state": "on", "source": source, "duration_s": seconds, "reason": command.get("reason", "")})
        self._after(seconds, lambda: self._pump_done(source, seconds))

    def backfill(self, store: DeviceStore, hours: float = 24, step_min: float = 5) -> list[SensorReading]:
        """Give the dashboard a past day to show, and return those readings. Works backwards from the
        current soil moisture: the soil dried, and whenever it got dry the simulated owner watered it."""
        now = datetime.now(timezone.utc)
        step = timedelta(minutes=step_min)
        soil = self.soil
        readings: list[SensorReading] = []
        waterings: list[datetime] = []
        for i in range(int(hours * 60 / step_min) + 1):
            at = now - i * step
            temperature, humidity = self._climate(at)
            readings.append(
                SensorReading(
                    device_id=self.device_id,
                    timestamp=at,
                    soil_moisture=round(soil, 1),
                    temperature=round(temperature, 1),
                    humidity=round(humidity, 1),
                )
            )
            soil += _drying_rate(temperature) * step_min / 60  # one step earlier, the soil was wetter
            if soil > WATERED_TO:  # ...unless it was watered in between
                waterings.append(at - step / 2)
                soil = DRY_AT + self.rng.uniform(-2, 2)

        readings.reverse()
        for reading in readings:
            store.record_reading(reading)
        for at in reversed(waterings):
            store.record_pump_state(
                self.device_id, {"state": "on", "source": "manual", "duration_s": 12, "reason": "Watered by hand"}, at
            )
            store.record_pump_state(
                self.device_id, {"state": "off", "source": "manual", "ran_s": 12, "result": "done"}, at + timedelta(seconds=12)
            )
        return readings

    # ------------------------------------------------------------------ helpers

    def _pump_done(self, source: str, seconds: float) -> None:
        with self._lock:
            self.soil = min(self.soil + SOIL_PER_PUMP_SECOND * seconds, 95.0)
            self._pump_running = False
            self._pump_stopped = time.monotonic()
        self._deliver(
            self.topics.pump_state(self.device_id), {"state": "off", "source": source, "ran_s": seconds, "result": "done"}
        )

    def _climate(self, at: datetime) -> tuple[float, float]:
        """A room that is warmest mid-afternoon and coolest before dawn, in this computer's local time."""
        local = at.astimezone()
        day = math.sin(2 * math.pi * (local.hour + local.minute / 60 - 9) / 24)
        return 28 + 3 * day + self.rng.uniform(-0.2, 0.2), 66 - 9 * day + self.rng.uniform(-1, 1)

    def _deliver(self, topic: str, payload: dict | str) -> None:
        body = payload if isinstance(payload, str) else json.dumps(payload)
        if self.on_message:
            self.on_message(self, None, SimpleNamespace(topic=topic, payload=body.encode()))

    def _after(self, seconds: float, fn: Callable[[], None]) -> None:
        """Run fn after `seconds` (the tests replace this to skip the wait)."""
        timer = threading.Timer(seconds, fn)
        timer.daemon = True
        timer.start()
