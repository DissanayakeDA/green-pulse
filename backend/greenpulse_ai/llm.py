"""LLM integration: one place that decides which chat model the agents use (or none)."""

from __future__ import annotations

import logging
import os

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from .config import Settings

log = logging.getLogger(__name__)

# API-key variable per LangChain provider. A missing key switches the agents to offline mode.
PROVIDER_API_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
}


def create_chat_model(settings: Settings) -> BaseChatModel | None:
    """Return the configured chat model, or None when the agents should run on rules only."""
    if settings.offline:
        log.info("Offline mode: agents use rule-based reasoning, no LLM calls")
        return None

    provider = settings.llm_model.split(":", 1)[0] if ":" in settings.llm_model else "openai"
    key_var = PROVIDER_API_KEYS.get(provider)
    if key_var and not os.getenv(key_var):
        log.warning("%s is not set; running in offline (rule-based) mode", key_var)
        return None

    kwargs: dict = {"timeout": settings.llm_timeout_s, "max_retries": 2}
    if settings.llm_temperature is not None:
        kwargs["temperature"] = settings.llm_temperature
    if settings.llm_reasoning_effort:
        kwargs["reasoning_effort"] = settings.llm_reasoning_effort
    return init_chat_model(settings.llm_model, **kwargs)
