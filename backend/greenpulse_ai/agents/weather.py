"""Weather Agent: summarises the forecast that affects an indoor plant (heat dries the soil faster,
humid rainy weather slows it down).

OpenMeteoWeatherAgent reads the live forecast from Open-Meteo (free, no API key). DummyWeatherAgent
reads a hardcoded forecast (see dummy_data) for the offline demo and the tests. Both produce the same
WeatherReport, and any class with a `run() -> WeatherReport` method can be passed to
orchestrator.build_service().
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Protocol

from ..schemas import WeatherReport

log = logging.getLogger(__name__)

HEAT_ALERT_C = 33.0
RAIN_LIKELY_PERCENT = 60

# WMO weather interpretation codes, as returned by Open-Meteo.
WMO_CONDITIONS = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    56: "freezing drizzle",
    57: "freezing drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "freezing rain",
    67: "freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light rain showers",
    81: "rain showers",
    82: "violent rain showers",
    85: "snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "thunderstorm with hail",
}


class WeatherAgent(Protocol):
    name: str

    def run(self) -> WeatherReport: ...


def summarise_forecast(forecast: dict, location: str, source: str, period: str = "") -> WeatherReport:
    """forecast: condition, temp_c, max_temp_c, humidity, rain_probability. period, e.g. " in the next 12 h",
    says which time span max_temp_c and rain_probability cover."""
    f = forecast
    heat_alert = f["max_temp_c"] >= HEAT_ALERT_C
    rain_expected = f["rain_probability"] >= RAIN_LIKELY_PERCENT

    summary = (
        f"{f['condition'].capitalize()} in {location}: {f['temp_c']:.0f}°C now, {f['humidity']:.0f}% humidity; "
        f"high of {f['max_temp_c']:.0f}°C and {f['rain_probability']:.0f}% chance of rain{period}."
    )
    if heat_alert:
        summary += " Hot day: indoor soil will dry faster than usual."
    elif rain_expected:
        summary += " Humid, rainy weather: indoor soil will dry slowly."

    return WeatherReport(
        source=source,
        location=location,
        summary=summary,
        temperature_c=f["temp_c"],
        max_temperature_c=f["max_temp_c"],
        humidity=f["humidity"],
        rain_expected=rain_expected,
        heat_alert=heat_alert,
    )


class DummyWeatherAgent:
    """Summarises a hardcoded forecast dict (see dummy_data) instead of calling a weather API."""

    name = "weather"

    def __init__(self, forecast: dict, location: str):
        self.forecast = forecast
        self.location = location

    def run(self) -> WeatherReport:
        return summarise_forecast(self.forecast, self.location, "dummy")


def _get_json(url: str, params: dict, timeout_s: float) -> dict:
    request = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}", headers={"User-Agent": "GreenPulse/1.0"}
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return json.load(response)


def parse_open_meteo(data: dict) -> dict:
    """Turn an Open-Meteo /v1/forecast response into the forecast dict summarise_forecast() takes."""
    current, hourly = data["current"], data["hourly"]
    temperatures = [t for t in hourly["temperature_2m"] if t is not None]
    rain = [p for p in hourly["precipitation_probability"] if p is not None]
    return {
        "condition": WMO_CONDITIONS.get(current["weather_code"], "unknown weather"),
        "temp_c": current["temperature_2m"],
        "max_temp_c": max([current["temperature_2m"], *temperatures]),
        "humidity": current["relative_humidity_2m"],
        "rain_probability": max(rain, default=0),
    }


class OpenMeteoWeatherAgent:
    """Live forecast for the plant's location from Open-Meteo (https://open-meteo.com, no API key).

    The forecast changes slowly, so one fetch is reused for `cache_s`. If a fetch fails, the last
    forecast is used for up to `max_stale_s`; after that the error propagates and the orchestrator
    reports the weather as unavailable.
    """

    name = "weather"
    URL = "https://api.open-meteo.com/v1/forecast"
    FORECAST_HOURS = 12

    def __init__(
        self,
        location: str,
        latitude: float,
        longitude: float,
        cache_s: float = 900,
        max_stale_s: float = 3 * 3600,
        timeout_s: float = 10,
        fetch: Callable[[str, dict, float], dict] = _get_json,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.location = location
        self.params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,relative_humidity_2m,weather_code",
            "hourly": "temperature_2m,precipitation_probability",
            "forecast_hours": self.FORECAST_HOURS,
            "timezone": "auto",
        }
        self.cache_s = cache_s
        self.max_stale_s = max_stale_s
        self.timeout_s = timeout_s
        self._fetch = fetch
        self._clock = clock
        self._last: tuple[float, WeatherReport] | None = None

    def run(self) -> WeatherReport:
        now = self._clock()
        if self._last and now - self._last[0] < self.cache_s:
            return self._last[1]
        try:
            forecast = parse_open_meteo(self._fetch(self.URL, self.params, self.timeout_s))
        except Exception:
            if self._last and now - self._last[0] < self.max_stale_s:
                log.warning("Open-Meteo request failed; reusing the forecast from %.0f min ago", (now - self._last[0]) / 60)
                return self._last[1]
            raise
        report = summarise_forecast(forecast, self.location, "open-meteo", f" in the next {self.FORECAST_HOURS} h")
        self._last = (now, report)
        return report
