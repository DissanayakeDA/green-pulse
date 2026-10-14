"""Ideal growing ranges per plant type. The Environment Agent checks readings against these.

The built-in profiles below are always available. The owner can add more from the dashboard
(plant_library.py); `checkpoint()` keeps every profile, typed in or drafted by the LLM, within what
the sensors can measure and what makes sense for a houseplant.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

Range = tuple[float, float]


@dataclass(frozen=True)
class PlantProfile:
    key: str
    name: str
    moisture: Range  # soil moisture %, calibrated capacitive sensor
    temperature: Range  # deg C
    humidity: Range  # % RH
    care_notes: str
    scientific_name: str = ""
    source: str = "built-in"  # built-in | ai (drafted by the LLM, reviewed by the owner) | custom

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> PlantProfile:
        return cls(
            key=str(data["key"]),
            name=str(data["name"]),
            moisture=_range(data["moisture"]),
            temperature=_range(data["temperature"]),
            humidity=_range(data["humidity"]),
            care_notes=str(data.get("care_notes", "")),
            scientific_name=str(data.get("scientific_name", "")),
            source=str(data.get("source", "custom")),
        )


def _range(value) -> Range:
    low, high = value
    return float(low), float(high)


PROFILES: dict[str, PlantProfile] = {
    profile.key: profile
    for profile in (
        PlantProfile(
            key="pothos",
            name="Pothos (Money Plant)",
            scientific_name="Epipremnum aureum",
            moisture=(35, 65),
            temperature=(18, 32),
            humidity=(40, 80),
            care_notes="Let the top few cm of soil dry between waterings; soggy soil causes root rot. "
            "Prefers bright indirect light.",
        ),
        PlantProfile(
            key="snake_plant",
            name="Snake Plant",
            scientific_name="Dracaena trifasciata",
            moisture=(15, 40),
            temperature=(16, 32),
            humidity=(30, 70),
            care_notes="Very drought tolerant; overwatering is the most common cause of death.",
        ),
        PlantProfile(
            key="peace_lily",
            name="Peace Lily",
            scientific_name="Spathiphyllum wallisii",
            moisture=(45, 75),
            temperature=(18, 29),
            humidity=(50, 85),
            care_notes="Droops visibly when thirsty; likes humid air; keep out of direct sun.",
        ),
        PlantProfile(
            key="generic",
            name="Generic Houseplant",
            moisture=(30, 65),
            temperature=(16, 30),
            humidity=(40, 75),
            care_notes="Water when the top of the soil is dry; avoid standing water.",
        ),
    )
}


def get_profile(key: str) -> PlantProfile:
    try:
        return PROFILES[key]
    except KeyError:
        raise ValueError(f"Unknown plant profile '{key}'. Choose one of: {', '.join(PROFILES)}") from None


# --------------------------------------------------------------------------- checkpoint

# (lowest allowed, highest allowed, narrowest sensible range). Soil moisture is the capacitive sensor's
# 0-100 % scale, where neither end is a real growing condition; temperatures are for indoor plants.
LIMITS: dict[str, tuple[float, float, float]] = {
    "moisture": (5, 95, 10),
    "temperature": (5, 40, 4),
    "humidity": (10, 95, 15),
}
LABELS = {"moisture": ("Soil moisture", "%"), "temperature": ("Temperature", " °C"), "humidity": ("Humidity", "%")}


def checkpoint(ranges: dict[str, Range]) -> tuple[dict[str, Range], list[str]]:
    """Bring each ideal range within the limits above, fixing a swapped or too-narrow range.

    Returns the corrected ranges and a note for every change, so whoever reviews the profile (and the
    dashboard) sees what was adjusted. An empty list means the ranges passed unchanged.
    """
    fixed: dict[str, Range] = {}
    notes: list[str] = []
    for field, (lowest, highest, span) in LIMITS.items():
        label, unit = LABELS[field]
        low, high = ranges[field]
        original = (low, high)
        if low > high:
            low, high = high, low
        low = min(max(low, lowest), highest - span)
        high = min(max(high, low + span), highest)
        low, high = round(low, 1), round(high, 1)
        if (low, high) != original:
            notes.append(
                f"{label}: {original[0]:g}-{original[1]:g}{unit} adjusted to {low:g}-{high:g}{unit} "
                f"(allowed {lowest:g}-{highest:g}{unit}, at least {span:g} apart)"
            )
        fixed[field] = (low, high)
    return fixed, notes
