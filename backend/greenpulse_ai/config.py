"""Runtime settings, read from environment variables (or a .env file next to the backend)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _optional(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # "<provider>:<model>" as understood by LangChain's init_chat_model.
    llm_model: str = "openai:gpt-5.4-mini"
    llm_temperature: float | None = None  # leave unset for reasoning models (GPT-5 family)
    llm_reasoning_effort: str | None = None  # e.g. "low" for faster GPT-5 responses
    llm_timeout_s: float = 60.0
    offline: bool = False  # True = never call the LLM; agents use rule-based reasoning

    device_id: str = "greenpulse-01"
    plant_profile: str = "pothos"
    location: str = "Colombo, LK"
    topic_prefix: str = "greenpulse"

    # The ESP32 publishes often; the (paid) LLM pipeline only runs when something is worth re-analysing.
    analysis_interval_s: int = 300
    moisture_change_trigger: float = 5.0

    # MQTT broker used by the live bridge (python -m greenpulse_ai.bridge). A local Mosquitto needs only
    # the host; AWS IoT Core needs port 8883 plus the CA, certificate and private-key files.
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_client_id: str = "greenpulse-backend"
    mqtt_ca_file: str | None = None
    mqtt_cert_file: str | None = None
    mqtt_key_file: str | None = None

    # Auto-watering. Off until enabled here or with the Node-RED switch. The ESP32 enforces its own
    # hard limits (maximum run time, rest time, wet-soil cut-off) on top of these.
    auto_watering: bool = False
    water_pulse_s: float = 5.0  # one short pulse, then let it soak before the sensor is trusted again
    water_cooldown_s: int = 1800
    water_max_per_day: int = 6

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        temperature = _optional("LLM_TEMPERATURE")
        return cls(
            llm_model=_optional("LLM_MODEL") or cls.llm_model,
            llm_temperature=float(temperature) if temperature else None,
            llm_reasoning_effort=_optional("LLM_REASONING_EFFORT"),
            llm_timeout_s=float(_optional("LLM_TIMEOUT_S") or cls.llm_timeout_s),
            offline=_flag("GREENPULSE_OFFLINE"),
            device_id=_optional("DEVICE_ID") or cls.device_id,
            plant_profile=_optional("PLANT_PROFILE") or cls.plant_profile,
            location=_optional("LOCATION") or cls.location,
            topic_prefix=_optional("MQTT_TOPIC_PREFIX") or cls.topic_prefix,
            analysis_interval_s=int(_optional("ANALYSIS_INTERVAL_S") or cls.analysis_interval_s),
            moisture_change_trigger=float(_optional("MOISTURE_CHANGE_TRIGGER") or cls.moisture_change_trigger),
            mqtt_host=_optional("MQTT_HOST") or cls.mqtt_host,
            mqtt_port=int(_optional("MQTT_PORT") or cls.mqtt_port),
            mqtt_username=_optional("MQTT_USERNAME"),
            mqtt_password=_optional("MQTT_PASSWORD"),
            mqtt_client_id=_optional("MQTT_CLIENT_ID") or cls.mqtt_client_id,
            mqtt_ca_file=_optional("MQTT_CA_FILE"),
            mqtt_cert_file=_optional("MQTT_CERT_FILE"),
            mqtt_key_file=_optional("MQTT_KEY_FILE"),
            auto_watering=_flag("AUTO_WATERING"),
            water_pulse_s=float(_optional("WATER_PULSE_S") or cls.water_pulse_s),
            water_cooldown_s=int(_optional("WATER_COOLDOWN_S") or cls.water_cooldown_s),
            water_max_per_day=int(_optional("WATER_MAX_PER_DAY") or cls.water_max_per_day),
        )
