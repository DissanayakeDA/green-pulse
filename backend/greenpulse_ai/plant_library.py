"""The plants the system knows, and which plant each device is watching.

Built-in profiles (plant_profiles.PROFILES) are always there; the owner adds more from the dashboard.
Added profiles and the device-to-plant choices are saved to a JSON file (PLANTS_FILE), so they survive
a restart. Every agent asks `profile_for(device_id)` for the plant to judge a reading against.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from pathlib import Path

from .plant_profiles import PROFILES, PlantProfile, Range, checkpoint

log = logging.getLogger(__name__)


class PlantLibrary:
    """Thread-safe: API requests change it while the analysis worker reads it."""

    def __init__(self, path: Path | str | None = None, default_key: str = "pothos"):
        self.path = Path(path) if path else None
        self.default_key = default_key if default_key in PROFILES else "pothos"
        self._lock = threading.Lock()
        self._custom: dict[str, PlantProfile] = {}
        self._devices: dict[str, str] = {}
        self._load()

    # ------------------------------------------------------------------ reads

    def profiles(self) -> list[PlantProfile]:
        with self._lock:
            return [*PROFILES.values(), *self._custom.values()]

    def get(self, key: str) -> PlantProfile:
        with self._lock:
            profile = PROFILES.get(key) or self._custom.get(key)
        if profile is None:
            raise KeyError(f"No plant profile called '{key}'")
        return profile

    def assigned_key(self, device_id: str) -> str:
        with self._lock:
            key = self._devices.get(device_id, self.default_key)
            return key if key in PROFILES or key in self._custom else self.default_key

    def profile_for(self, device_id: str) -> PlantProfile:
        return self.get(self.assigned_key(device_id))

    def devices_using(self, key: str) -> list[str]:
        with self._lock:
            return sorted(device for device, assigned in self._devices.items() if assigned == key)

    # ------------------------------------------------------------------ changes (the dashboard)

    def add(
        self,
        name: str,
        ranges: dict[str, Range],
        care_notes: str = "",
        scientific_name: str = "",
        source: str = "custom",
    ) -> PlantProfile:
        """Save a new profile. Raises ValueError if the ranges don't pass the checkpoint."""
        _require_valid(ranges)
        with self._lock:
            key = self._unique_key(name)
            profile = _profile(key, name, ranges, care_notes, scientific_name, source)
            self._custom[key] = profile
            self._save()
        return profile

    def update(
        self,
        key: str,
        name: str,
        ranges: dict[str, Range],
        care_notes: str = "",
        scientific_name: str = "",
        source: str = "custom",
    ) -> PlantProfile:
        _require_valid(ranges)
        with self._lock:
            if key in PROFILES:
                raise PermissionError("Built-in profiles can't be changed; add a new plant instead")
            if key not in self._custom:
                raise KeyError(f"No plant profile called '{key}'")
            profile = _profile(key, name, ranges, care_notes, scientific_name, source)
            self._custom[key] = profile
            self._save()
        return profile

    def delete(self, key: str) -> list[str]:
        """Remove an added profile. Devices that used it go back to the default; returns their IDs."""
        with self._lock:
            if key in PROFILES:
                raise PermissionError("Built-in profiles can't be deleted")
            if key not in self._custom:
                raise KeyError(f"No plant profile called '{key}'")
            del self._custom[key]
            moved = sorted(device for device, assigned in self._devices.items() if assigned == key)
            for device in moved:
                del self._devices[device]
            self._save()
        return moved

    def assign(self, device_id: str, key: str) -> PlantProfile:
        profile = self.get(key)
        with self._lock:
            self._devices[device_id] = key
            self._save()
        log.info("%s  now watching %s", device_id, profile.name)
        return profile

    # ------------------------------------------------------------------ storage

    def _unique_key(self, name: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "plant"
        key, n = base, 2
        while key in PROFILES or key in self._custom:
            key, n = f"{base}-{n}", n + 1
        return key

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for item in data.get("plants", []):
                profile = PlantProfile.from_dict(item)
                if profile.key not in PROFILES:
                    self._custom[profile.key] = profile
            self._devices = {str(d): str(k) for d, k in data.get("devices", {}).items()}
        except (ValueError, KeyError, TypeError) as exc:
            log.error("Can't read %s (%s); starting with the built-in plants only", self.path, exc)

    def _save(self) -> None:
        """Write the whole file atomically, so a crash never leaves half a file. Call with the lock held."""
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"plants": [p.as_dict() for p in self._custom.values()], "devices": self._devices}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)


def _require_valid(ranges: dict[str, Range]) -> None:
    _, problems = checkpoint(ranges)
    if problems:
        raise ValueError("; ".join(problems))


def _profile(key: str, name: str, ranges: dict[str, Range], care_notes: str, scientific_name: str, source: str) -> PlantProfile:
    low_high = {field: (float(ranges[field][0]), float(ranges[field][1])) for field in ("moisture", "temperature", "humidity")}
    return PlantProfile(
        key=key,
        name=name.strip(),
        moisture=low_high["moisture"],
        temperature=low_high["temperature"],
        humidity=low_high["humidity"],
        care_notes=care_notes.strip(),
        scientific_name=scientific_name.strip(),
        source=source,
    )
