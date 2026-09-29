"""Hardcoded dummy data standing in for the ESP32, the weather API and the email inbox.

Each scenario holds a short series of sensor readings (so the moisture trend can be computed), a
weather forecast and an inbox. Ranges are for the default "pothos" profile: soil 35-65 %,
18-32 deg C, 40-80 % RH.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .schemas import SensorReading


def _ago(hours: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours)


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    # (minutes before now, soil moisture %, temperature deg C, humidity %); None = failed sensor read
    reading_series: tuple[tuple[int, float | None, float | None, float | None], ...]
    weather: dict
    messages: list[dict]

    def readings(self, device_id: str = "greenpulse-01") -> list[SensorReading]:
        now = datetime.now(timezone.utc)
        return [
            SensorReading(
                device_id=device_id,
                timestamp=now - timedelta(minutes=minutes_ago),
                soil_moisture=moisture,
                temperature=temperature,
                humidity=humidity,
            )
            for minutes_ago, moisture, temperature, humidity in self.reading_series
        ]


NEWSLETTER = {
    "from": "deals@shop.example.com",
    "subject": "Weekend sale: 30% off headphones",
    "body": "Don't miss our biggest sale of the season.",
    "received": _ago(5),
}

SCENARIOS: dict[str, Scenario] = {
    s.key: s
    for s in (
        Scenario(
            key="healthy",
            title="Everything is fine",
            reading_series=((120, 55.0, 26.5, 64.0), (60, 54.6, 26.8, 63.0), (0, 54.2, 27.0, 63.0)),
            weather={"condition": "partly cloudy", "temp_c": 29, "max_temp_c": 30, "humidity": 74, "rain_probability": 30},
            messages=[NEWSLETTER],
        ),
        Scenario(
            key="drying_fast",
            title="Soil drying fast on a hot afternoon",
            reading_series=(
                (360, 47.0, 28.0, 60.0),
                (240, 44.1, 29.1, 57.0),
                (120, 41.5, 30.0, 54.0),
                (0, 38.5, 30.5, 52.0),
            ),
            weather={"condition": "sunny", "temp_c": 32, "max_temp_c": 34, "humidity": 58, "rain_probability": 10},
            messages=[
                NEWSLETTER,
                {
                    "from": "reminders@plantdiary.example.com",
                    "subject": "Watering reminder: Money plant",
                    "body": "Your money plant is due for watering tomorrow (every 4 days).",
                    "received": _ago(2),
                },
            ],
        ),
        Scenario(
            key="critically_dry",
            title="Soil almost bone dry during a heatwave",
            reading_series=((180, 18.0, 30.5, 42.0), (90, 16.1, 31.0, 40.0), (0, 14.0, 31.5, 38.0)),
            weather={"condition": "sunny", "temp_c": 34, "max_temp_c": 36, "humidity": 45, "rain_probability": 5},
            messages=[
                {
                    "from": "reminders@plantdiary.example.com",
                    "subject": "Missed: water the money plant",
                    "body": "You missed a scheduled watering 3 days ago.",
                    "received": _ago(72),
                }
            ],
        ),
        Scenario(
            key="overwatered",
            title="Soggy soil, but the fixed schedule says water today",
            reading_series=((120, 88.0, 24.5, 83.0), (60, 87.2, 24.4, 82.0), (0, 86.0, 24.5, 82.0)),
            weather={"condition": "heavy rain", "temp_c": 25, "max_temp_c": 27, "humidity": 92, "rain_probability": 90},
            messages=[
                {
                    "from": "reminders@plantdiary.example.com",
                    "subject": "Watering reminder: Money plant",
                    "body": "Today is watering day for your money plant (every 3 days).",
                    "received": _ago(1),
                }
            ],
        ),
        Scenario(
            key="heat_stress",
            title="Room overheating next to a sunny window",
            reading_series=((240, 58.0, 33.0, 40.0), (120, 53.1, 35.2, 36.0), (0, 48.0, 36.8, 33.0)),
            weather={"condition": "sunny", "temp_c": 35, "max_temp_c": 37, "humidity": 50, "rain_probability": 0},
            messages=[NEWSLETTER],
        ),
        Scenario(
            key="sensor_fault",
            title="Temperature/humidity sensor stopped responding",
            reading_series=((60, 51.5, 27.0, 62.0), (30, 51.2, None, None), (0, 51.0, None, None)),
            weather={"condition": "cloudy", "temp_c": 28, "max_temp_c": 29, "humidity": 78, "rain_probability": 40},
            messages=[NEWSLETTER],
        ),
        Scenario(
            key="going_on_trip",
            title="Plant is fine, but the owner travels this weekend",
            reading_series=((180, 47.5, 27.0, 61.0), (0, 46.0, 27.2, 60.0)),
            weather={"condition": "partly cloudy", "temp_c": 30, "max_temp_c": 31, "humidity": 70, "rain_probability": 20},
            messages=[
                NEWSLETTER,
                {
                    "from": "bookings@travel.example.com",
                    "subject": "Booking confirmed: Kandy hill-country trip",
                    "body": "Your trip is confirmed from this Friday to Monday (3 nights).",
                    "received": _ago(20),
                },
            ],
        ),
    )
}

DEFAULT_SCENARIO = "drying_fast"


def simulate_readings(
    device_id: str = "greenpulse-01",
    count: int = 48,
    step_minutes: int = 10,
    start_moisture: float = 46.0,
    seed: int = 7,
) -> Iterator[SensorReading]:
    """Fake ESP32: a day-cycle of temperature/humidity, soil that dries faster when it is hot,
    and a simulated user who waters the plant once the soil gets very dry."""
    rng = random.Random(seed)
    start = datetime.now(timezone.utc)
    moisture = start_moisture
    for i in range(count):
        hours = i * step_minutes / 60
        day = math.sin(2 * math.pi * hours / 24)  # starts mid-morning, peaks ~6 h later
        temperature = 27 + 5 * day + rng.uniform(-0.3, 0.3)
        humidity = 65 - 12 * day + rng.uniform(-1.5, 1.5)
        if i:
            drying_per_hour = 2.8 + 0.25 * (temperature - 27)
            moisture -= drying_per_hour * step_minutes / 60 + rng.uniform(-0.1, 0.1)
        if moisture < 27:
            moisture = 70.0  # the user waters the plant
        yield SensorReading(
            device_id=device_id,
            timestamp=start + timedelta(minutes=i * step_minutes),
            soil_moisture=round(moisture, 1),
            temperature=round(temperature, 1),
            humidity=round(humidity, 1),
        )
