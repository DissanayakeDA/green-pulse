"""The four agents of the Multi-Agent Plant Doctor, and the Chat Agent that answers the owner's questions."""

from .chat import ChatAgent
from .environment import EnvironmentAgent
from .notification import DummyNotificationAgent, ImapNotificationAgent, NoMailboxAgent, NotificationAgent
from .plant_doctor import Diagnosis, PlantDoctorAgent
from .weather import DummyWeatherAgent, OpenMeteoWeatherAgent, WeatherAgent

__all__ = [
    "ChatAgent",
    "Diagnosis",
    "DummyNotificationAgent",
    "DummyWeatherAgent",
    "EnvironmentAgent",
    "ImapNotificationAgent",
    "NoMailboxAgent",
    "NotificationAgent",
    "OpenMeteoWeatherAgent",
    "PlantDoctorAgent",
    "WeatherAgent",
]
