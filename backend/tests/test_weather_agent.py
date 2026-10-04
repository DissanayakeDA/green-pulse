from urllib.error import URLError

import pytest

from greenpulse_ai.agents import DummyWeatherAgent, OpenMeteoWeatherAgent
from greenpulse_ai.agents.weather import parse_open_meteo, summarise_forecast
from greenpulse_ai.dummy_data import SCENARIOS

from conftest import open_meteo_response


class FakeFetch:
    """Stands in for the HTTP call: returns canned responses (or raises them) and records the requests."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[tuple[str, dict]] = []

    def __call__(self, url, params, timeout_s):
        self.requests.append((url, params))
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(response, Exception):
            raise response
        return response


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def agent(fetch, clock=None):
    return OpenMeteoWeatherAgent("Colombo, LK", 6.9271, 79.8612, fetch=fetch, clock=clock or Clock())


def test_parses_an_open_meteo_response():
    forecast = parse_open_meteo(open_meteo_response())
    assert forecast == {
        "condition": "overcast",
        "temp_c": 29.4,
        "max_temp_c": 30.1,  # the highest hourly value in the forecast window
        "humidity": 71,
        "rain_probability": 94,
    }


def test_missing_hourly_values_are_skipped():
    data = open_meteo_response(hourly_temps=(None, 31.0), rain=(None, None))
    forecast = parse_open_meteo(data)
    assert forecast["max_temp_c"] == 31.0
    assert forecast["rain_probability"] == 0


def test_unknown_weather_code():
    assert parse_open_meteo(open_meteo_response(code=42))["condition"] == "unknown weather"


def test_live_report():
    fetch = FakeFetch(open_meteo_response())
    report = agent(fetch).run()

    url, params = fetch.requests[0]
    assert url == "https://api.open-meteo.com/v1/forecast"
    assert (params["latitude"], params["longitude"]) == (6.9271, 79.8612)
    assert report.source == "open-meteo"
    assert report.location == "Colombo, LK"
    assert report.rain_expected and not report.heat_alert
    assert report.summary.startswith("Overcast in Colombo, LK: 29°C now, 71% humidity; high of 30°C")
    assert "in the next 12 h" in report.summary
    assert "dry slowly" in report.summary


def test_heat_alert():
    report = agent(FakeFetch(open_meteo_response(code=0, hourly_temps=(32.0, 34.5), rain=(5, 0)))).run()
    assert report.heat_alert and not report.rain_expected
    assert "dry faster" in report.summary


def test_forecast_is_cached():
    fetch, clock = FakeFetch(open_meteo_response()), Clock()
    weather = agent(fetch, clock)
    weather.run()
    clock.now += 600
    weather.run()
    assert len(fetch.requests) == 1
    clock.now += 600  # 20 min after the first fetch, past the 15 min cache
    weather.run()
    assert len(fetch.requests) == 2


def test_a_failed_fetch_reuses_the_last_forecast():
    fetch, clock = FakeFetch(open_meteo_response(), URLError("no network")), Clock()
    weather = agent(fetch, clock)
    first = weather.run()
    clock.now += 3600
    assert weather.run() == first


def test_a_failed_fetch_without_a_recent_forecast_raises():
    # The orchestrator turns the error into an "unavailable" weather report.
    with pytest.raises(URLError):
        agent(FakeFetch(URLError("no network"))).run()

    fetch, clock = FakeFetch(open_meteo_response(), URLError("no network")), Clock()
    weather = agent(fetch, clock)
    weather.run()
    clock.now += 4 * 3600  # older than the 3 h staleness limit
    with pytest.raises(URLError):
        weather.run()


def test_dummy_agent_uses_the_same_summary():
    forecast = SCENARIOS["heat_stress"].weather
    assert DummyWeatherAgent(forecast, "Colombo, LK").run() == summarise_forecast(forecast, "Colombo, LK", "dummy")
