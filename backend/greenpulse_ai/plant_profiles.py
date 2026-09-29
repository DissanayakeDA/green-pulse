"""Ideal growing ranges per plant type. The Environment Agent checks readings against these."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlantProfile:
    key: str
    name: str
    moisture: tuple[float, float]  # soil moisture %, calibrated capacitive sensor
    temperature: tuple[float, float]  # deg C
    humidity: tuple[float, float]  # % RH
    care_notes: str


PROFILES: dict[str, PlantProfile] = {
    profile.key: profile
    for profile in (
        PlantProfile(
            key="pothos",
            name="Pothos (Money Plant)",
            moisture=(35, 65),
            temperature=(18, 32),
            humidity=(40, 80),
            care_notes="Let the top few cm of soil dry between waterings; soggy soil causes root rot. "
            "Prefers bright indirect light.",
        ),
        PlantProfile(
            key="snake_plant",
            name="Snake Plant",
            moisture=(15, 40),
            temperature=(16, 32),
            humidity=(30, 70),
            care_notes="Very drought tolerant; overwatering is the most common cause of death.",
        ),
        PlantProfile(
            key="peace_lily",
            name="Peace Lily",
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
