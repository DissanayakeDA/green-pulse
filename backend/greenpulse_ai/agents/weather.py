"""Weather Agent interface + a stand-in that reads hardcoded forecast data.

The real Weather Agent (live weather API) is owned by Thashmila P H J. Any class with a
`run() -> WeatherReport` method can replace DummyWeatherAgent in orchestrator.build_service().
"""

from __future__ import annotations

from typing import Protocol

from ..schemas import WeatherReport

HEAT_ALERT_C = 33.0
RAIN_LIKELY_PERCENT = 60


class WeatherAgent(Protocol):
    name: str

    def run(self) -> WeatherReport: ...


class DummyWeatherAgent:
    """Summarises a hardcoded forecast dict (see dummy_data) instead of calling a weather API."""

    name = "weather"

    def __init__(self, forecast: dict, location: str):
        self.forecast = forecast
        self.location = location

    def run(self) -> WeatherReport:
        f = self.forecast
        heat_alert = f["max_temp_c"] >= HEAT_ALERT_C
        rain_expected = f["rain_probability"] >= RAIN_LIKELY_PERCENT

        summary = (
            f"{f['condition'].capitalize()} in {self.location}: {f['temp_c']:.0f}°C now, "
            f"high of {f['max_temp_c']:.0f}°C, {f['humidity']:.0f}% humidity, "
            f"{f['rain_probability']}% chance of rain."
        )
        if heat_alert:
            summary += " Hot day: indoor soil will dry faster than usual."
        elif rain_expected:
            summary += " Humid, rainy weather: indoor soil will dry slowly."

        return WeatherReport(
            source="dummy",
            location=self.location,
            summary=summary,
            temperature_c=f["temp_c"],
            max_temperature_c=f["max_temp_c"],
            humidity=f["humidity"],
            rain_expected=rain_expected,
            heat_alert=heat_alert,
        )
