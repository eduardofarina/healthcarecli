"""Config file management — platform-aware paths, read/write JSON profiles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

APP_NAME = "healthcarecli"


def config_dir() -> Path:
    """Return (and create if needed) the platform config directory."""
    path = Path(user_config_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path


def profiles_path() -> Path:
    return config_dir() / "profiles.json"


def _load_all() -> dict[str, Any]:
    p = profiles_path()
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _save_all(data: dict[str, Any]) -> None:
    with profiles_path().open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


# ── Section-scoped helpers used by each module ───────────────────────────────

def list_profiles(section: str) -> dict[str, Any]:
    return _load_all().get(section, {})


def get_profile(section: str, name: str) -> dict[str, Any] | None:
    return _load_all().get(section, {}).get(name)


def save_profile(section: str, name: str, data: dict[str, Any]) -> None:
    all_profiles = _load_all()
    all_profiles.setdefault(section, {})[name] = data
    _save_all(all_profiles)


def delete_profile(section: str, name: str) -> bool:
    """Return True if the profile existed and was deleted."""
    all_profiles = _load_all()
    section_data = all_profiles.get(section, {})
    if name not in section_data:
        return False
    del section_data[name]
    all_profiles[section] = section_data
    _save_all(all_profiles)
    return True
