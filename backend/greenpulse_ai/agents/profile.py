"""Plant Profile Agent: drafts the care profile for a plant the owner names on the dashboard.

Every plant needs different care, so GreenPulse judges readings against the profile of the plant
being watched. From a plant's name, the LLM suggests its ideal soil-moisture, temperature and
humidity ranges and short care notes. The draft then passes the checkpoint
(plant_profiles.checkpoint), which keeps each range within what the sensors measure and fixes a
swapped or too-narrow range, listing every change. The owner reviews the draft before saving it.

Without an LLM, or if it fails, a built-in profile with the same name is used, or typical ranges for
the kind of plant the name suggests (a cactus, a fern), or general houseplant ranges.
"""

from __future__ import annotations

import logging
import re

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from ..plant_profiles import PROFILES, PlantProfile, Range, checkpoint
from ..prompts import PROFILE_PROMPT
from ..schemas import PlantCareProfile

log = logging.getLogger(__name__)


class ProfileDraft(BaseModel):
    """A suggested profile for the owner to review. Nothing is saved until they do."""

    name: str
    scientific_name: str
    moisture: Range
    temperature: Range
    humidity: Range
    care_notes: str
    recognised: bool
    source: str = Field(description="llm | rules | rules-fallback")
    model: str | None = None
    note: str = Field("", description="What the owner should know about this draft")
    checks: list[str] = Field(default_factory=list, description="What the checkpoint adjusted")


# Typical ranges by kind of plant, for suggestions without the LLM.
FAMILIES: list[tuple[tuple[str, ...], Range, Range, Range, str]] = [
    (
        ("cactus", "cacti", "succulent", "aloe", "jade", "haworthia", "echeveria", "agave", "sedum", "zz plant", "zamioculcas"),
        (10, 35),
        (15, 35),
        (20, 60),
        "Let the soil dry out completely between waterings; it rots in wet soil.",
    ),
    (
        ("fern", "calathea", "maranta", "orchid", "lily", "anthurium", "fittonia", "moss", "begonia"),
        (45, 75),
        (18, 28),
        (55, 85),
        "Keep the soil lightly moist and the air humid; don't let it dry out completely.",
    ),
]


class PlantProfileAgent:
    name = "plant_profile"

    def __init__(self, llm: BaseChatModel | None = None, model: str | None = None, location: str = ""):
        self._chain = (PROFILE_PROMPT | llm.with_structured_output(PlantCareProfile)) if llm else None
        self.model = model if llm else None
        self.location = location

    def draft(self, name: str) -> ProfileDraft:
        name = " ".join(name.split())
        if self._chain is None:
            return _checked(rule_based_profile(name))
        try:
            care: PlantCareProfile = self._chain.invoke({"name": name, "location": self.location or "a home"})
        except Exception:
            log.exception("Plant Profile Agent LLM call failed; using the rule-based suggestion")
            draft = rule_based_profile(name)
            return _checked(draft.model_copy(update={"source": "rules-fallback", "note": f"The AI couldn't be reached. {draft.note}"}))

        draft = ProfileDraft(
            name=care.common_name.strip() or name,
            scientific_name=care.scientific_name.strip(),
            moisture=(care.soil_moisture_min, care.soil_moisture_max),
            temperature=(care.temperature_min, care.temperature_max),
            humidity=(care.humidity_min, care.humidity_max),
            care_notes=care.care_notes.strip(),
            recognised=care.recognised,
            source="llm",
            model=self.model,
            note=""
            if care.recognised
            else "The AI didn't recognise this plant, so it suggested typical houseplant ranges. Check them before saving.",
        )
        return _checked(draft)


def rule_based_profile(name: str) -> ProfileDraft:
    """A built-in profile with the same name, else typical ranges for the kind of plant, else generic ones."""
    wanted = name.lower()
    for profile in PROFILES.values():
        if wanted in _names(profile):
            return _from_profile(name, profile, recognised=True, note=f"Uses the built-in {profile.name} profile.")

    for keywords, moisture, temperature, humidity, notes in FAMILIES:
        if any(re.search(rf"\b{re.escape(word)}", wanted) for word in keywords):
            return ProfileDraft(
                name=name,
                scientific_name="",
                moisture=moisture,
                temperature=temperature,
                humidity=humidity,
                care_notes=notes,
                recognised=True,
                source="rules",
                note="The AI is off, so these are typical ranges for this kind of plant. Check them before saving.",
            )

    return _from_profile(
        name,
        PROFILES["generic"],
        recognised=False,
        note="The AI is off and GreenPulse doesn't know this name, so these are general houseplant ranges. "
        "Adjust them for your plant.",
    )


def _names(profile: PlantProfile) -> set[str]:
    full = profile.name.lower()
    names = {full, profile.key.replace("_", " "), full.split(" (")[0], profile.scientific_name.lower()}
    names.update(re.findall(r"\((.*?)\)", full))  # "Pothos (Money Plant)" -> "money plant"
    return names - {""}


def _from_profile(name: str, profile: PlantProfile, recognised: bool, note: str) -> ProfileDraft:
    return ProfileDraft(
        name=name if not recognised else profile.name,
        scientific_name=profile.scientific_name,
        moisture=profile.moisture,
        temperature=profile.temperature,
        humidity=profile.humidity,
        care_notes=profile.care_notes,
        recognised=recognised,
        source="rules",
        note=note,
    )


def _checked(draft: ProfileDraft) -> ProfileDraft:
    """The checkpoint: keep the suggested ranges within the sensors' limits and say what changed."""
    ranges, checks = checkpoint({"moisture": draft.moisture, "temperature": draft.temperature, "humidity": draft.humidity})
    return draft.model_copy(update={**ranges, "checks": checks})
