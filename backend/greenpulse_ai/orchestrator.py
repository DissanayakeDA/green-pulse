"""Agent orchestration.

    SensorReading ─┬─> Environment Agent ─┐
                   │   Weather Agent ─────┼─> Plant Doctor Agent ─> CareResult ─> MQTT payloads
                   │   Notification Agent ┘        (+ guardrail)
                   └─> reading history (moisture trend)

PlantDoctorPipeline runs one analysis. PlantCareService is what the MQTT layer talks to: it keeps
the reading history and decides which readings are worth a (paid, slow) LLM analysis.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import TypeVar

from langchain_core.language_models import BaseChatModel

from . import dummy_data
from .agents.environment import EnvironmentAgent
from .agents.notification import DummyNotificationAgent, ImapNotificationAgent, NoMailboxAgent, NotificationAgent
from .agents.plant_doctor import PlantDoctorAgent
from .agents.weather import DummyWeatherAgent, OpenMeteoWeatherAgent, WeatherAgent
from .config import Settings
from .plant_profiles import PlantProfile, get_profile
from .schemas import CareResult, NotificationReport, SensorReading, WeatherReport

log = logging.getLogger(__name__)

T = TypeVar("T")


class PlantDoctorPipeline:
    def __init__(
        self,
        environment: EnvironmentAgent,
        weather: WeatherAgent,
        notifications: NotificationAgent,
        doctor: PlantDoctorAgent,
        model: str | None = None,
    ):
        self.environment = environment
        self.weather = weather
        self.notifications = notifications
        self.doctor = doctor
        self.model = model

    def run(
        self,
        reading: SensorReading,
        history: Sequence[SensorReading] = (),
        trigger: str = "manual",
        profile: PlantProfile | None = None,
    ) -> CareResult:
        """`profile` is the plant this device watches; without it, the agents' default plant."""
        started = time.perf_counter()
        # The three analysis agents are independent (and mostly waiting on network I/O), so run them in parallel.
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="agent") as pool:
            environment_future = pool.submit(self.environment.run, reading, history, profile)
            weather_future = pool.submit(self.weather.run)
            notifications_future = pool.submit(self.notifications.run)

            environment = environment_future.result()  # no advice is possible without the sensor analysis
            weather = _result_or(
                weather_future,
                lambda: WeatherReport(source="unavailable", location="unknown", summary="Weather data is unavailable."),
            )
            notifications = _result_or(
                notifications_future,
                lambda: NotificationReport(source="unavailable", summary="Notifications are unavailable."),
            )

        diagnosis = self.doctor.run(environment, weather, notifications, profile)
        return CareResult(
            device_id=reading.device_id,
            generated_at=datetime.now(timezone.utc),
            trigger=trigger,
            reading=reading,
            environment=environment,
            weather=weather,
            notifications=notifications,
            advice=diagnosis.advice,
            doctor_source=diagnosis.source,
            model=self.model if diagnosis.source == "llm" or environment.source == "llm" else None,
            guardrail_note=diagnosis.guardrail_note,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )


def _result_or(future: Future[T], fallback: Callable[[], T]) -> T:
    """A failing external agent (weather API down, mailbox unreachable) must not block the care advice."""
    try:
        return future.result()
    except Exception:
        log.exception("Agent failed; continuing without its report")
        return fallback()


class PlantCareService:
    """Feed it every sensor reading; it returns a CareResult when a new analysis was run, else None."""

    def __init__(
        self,
        pipeline: PlantDoctorPipeline,
        analysis_interval_s: int = 300,
        moisture_change_trigger: float = 5.0,
        history_size: int = 720,
        profile_for: Callable[[str], PlantProfile] | None = None,
    ):
        self.pipeline = pipeline
        self.analysis_interval_s = analysis_interval_s
        self.moisture_change_trigger = moisture_change_trigger
        # Which plant each device watches (plant_library.PlantLibrary.profile_for); default: the agents' plant.
        self.profile_for = profile_for or (lambda device_id: pipeline.environment.profile)
        self._history: dict[str, deque[SensorReading]] = defaultdict(lambda: deque(maxlen=history_size))
        self._last_result: dict[str, CareResult] = {}
        self._last_profile: dict[str, PlantProfile] = {}

    def handle_reading(self, reading: SensorReading, force: bool = False) -> CareResult | None:
        history = self._history[reading.device_id]
        history.append(reading)
        profile = self.profile_for(reading.device_id)
        trigger = "forced" if force else self._analysis_trigger(reading, list(history), profile)
        if trigger is None:
            return None

        log.info("Running Plant Doctor for %s (%s)", reading.device_id, trigger)
        result = self.pipeline.run(reading, list(history), trigger=trigger, profile=profile)
        self._last_result[reading.device_id] = result
        self._last_profile[reading.device_id] = profile
        return result

    def last_result(self, device_id: str) -> CareResult | None:
        return self._last_result.get(device_id)

    def preload(self, readings: Sequence[SensorReading]) -> None:
        """Add past readings to the history without analysing them (demo mode's simulated past day), so
        the first analysis already knows the moisture trend."""
        for reading in readings:
            self._history[reading.device_id].append(reading)

    def _analysis_trigger(self, reading: SensorReading, history: list[SensorReading], profile: PlantProfile) -> str | None:
        last = self._last_result.get(reading.device_id)
        if last is None:
            return "first reading"
        if self._last_profile.get(reading.device_id) != profile:  # another plant, or its ranges were edited
            return "plant profile changed"
        # Reading timestamps (not wall-clock time) keep this deterministic for replayed or simulated data.
        if (reading.timestamp - last.reading.timestamp).total_seconds() >= self.analysis_interval_s:
            return "interval elapsed"
        if (
            reading.soil_moisture is not None
            and last.reading.soil_moisture is not None
            and abs(reading.soil_moisture - last.reading.soil_moisture) >= self.moisture_change_trigger
        ):
            return "moisture changed"
        baseline = self.pipeline.environment.evaluate(reading, history, profile).baseline_priority
        if baseline != last.environment.baseline_priority:
            return "sensor priority changed"
        return None


def build_pipeline(
    settings: Settings,
    llm: BaseChatModel | None,
    weather_agent: WeatherAgent | None = None,
    notification_agent: NotificationAgent | None = None,
) -> PlantDoctorPipeline:
    """Wire the agents together. Without explicit weather/notification agents they default to dummy
    stand-ins with neutral context (mild weather, no reminders), for the offline demo and the tests.
    The live bridge passes the real ones from live_context_agents()."""
    profile = get_profile(settings.plant_profile)
    neutral = dummy_data.SCENARIOS["healthy"]
    return PlantDoctorPipeline(
        environment=EnvironmentAgent(profile, llm),
        weather=weather_agent or DummyWeatherAgent(neutral.weather, settings.location),
        notifications=notification_agent or DummyNotificationAgent(neutral.messages),
        doctor=PlantDoctorAgent(profile, llm),
        model=settings.llm_model if llm else None,
    )


def live_context_agents(settings: Settings) -> tuple[WeatherAgent, NotificationAgent]:
    """The real Weather Agent (Open-Meteo forecast) and Notification Agent (IMAP mailbox). Without
    EMAIL_ADDRESS and EMAIL_APP_PASSWORD the notification report says email is not connected."""
    weather = OpenMeteoWeatherAgent(settings.location, settings.weather_latitude, settings.weather_longitude)
    if settings.email_address and settings.email_app_password:
        notifications: NotificationAgent = ImapNotificationAgent(
            settings.email_imap_host, settings.email_address, settings.email_app_password, settings.email_folder
        )
    else:
        notifications = NoMailboxAgent()
    return weather, notifications


def describe_context(settings: Settings) -> str:
    """One line naming the live context sources, for start-up messages."""
    if settings.email_address and settings.email_app_password:
        email = f"{settings.email_address} ({settings.email_folder})"
    else:
        email = "not connected (set EMAIL_ADDRESS and EMAIL_APP_PASSWORD in .env)"
    return (
        f"Weather: Open-Meteo for {settings.location} ({settings.weather_latitude}, {settings.weather_longitude}) | "
        f"email: {email}"
    )


def build_service(
    settings: Settings,
    llm: BaseChatModel | None,
    weather_agent: WeatherAgent | None = None,
    notification_agent: NotificationAgent | None = None,
    profile_for: Callable[[str], PlantProfile] | None = None,
) -> PlantCareService:
    """`profile_for` picks each device's plant (PlantLibrary.profile_for); without it, PLANT_PROFILE for all."""
    pipeline = build_pipeline(settings, llm, weather_agent, notification_agent)
    return PlantCareService(
        pipeline, settings.analysis_interval_s, settings.moisture_change_trigger, profile_for=profile_for
    )
