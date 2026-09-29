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
        )
