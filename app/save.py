"""Save/load game state snapshots as JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.domain import ClockTime
from app.settings import get_settings


class SaveSnapshot(BaseModel):
    """Snapshot of UI/game state for save/load."""

    version: int = 3
    day: int = 1
    time: ClockTime
    location: str = "South Clock Town"
    masks: list[str] = Field(default_factory=list)
    inventory: list[str] = Field(default_factory=list)
    quest_progress: list[str] = Field(default_factory=list)
    completed_objectives: list[str] = Field(default_factory=list)
    goal: str = ""
    migration_warning: str = ""

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_clock(cls, data):
        """Bring older save payloads up to the current snapshot version.

        Version 2 added the game-day clock: old saves stored wall-clock hours
        0-23 on an absolute day, so those early hours belong to the previous
        game day's night (old Day 2 02:00 is Day 1 26:00). The invalid pre-dawn
        hours of Day 1 clamp to the cycle start with a warning. Version 3 adds
        explicitly completed objectives, whose empty default keeps a version-2
        save loadable unchanged.

        args:
            data: the raw save payload.

        returns:
            dict: the migrated payload, or the input unchanged.
        """
        if not isinstance(data, dict):
            return data
        version = int(data.get("version", 1))
        if version >= 3:
            return data
        out = dict(data)
        out["version"] = 3
        raw_time = data.get("time")
        if version >= 2 or not isinstance(raw_time, dict):
            return out

        day = int(raw_time.get("day", data.get("day", 1)))
        hour = int(raw_time.get("hour", 6))
        minute = int(raw_time.get("minute", 0))
        warning = ""
        if hour < 6:
            day -= 1
            hour += 24
            if day < 1:
                day, hour, minute = 1, 6, 0
                warning = (
                    "Legacy save time was before Day 1 06:00; clamped to the start of the cycle."
                )
        out["day"] = day
        out["time"] = {"day": day, "hour": hour, "minute": minute}
        if warning:
            out["migration_warning"] = warning
        return out


DEFAULT_SAVE_NAME = "last_save.json"


def get_save_dir() -> Path:
    """Return the directory where save files are stored."""
    cache_dir = get_settings().rag.qdrant_path.parent
    save_dir = cache_dir.parent / "saves"
    save_dir.mkdir(parents=True, exist_ok=True)
    return save_dir


def get_save_path(filename: str = DEFAULT_SAVE_NAME) -> Path:
    """Return the path to a save file."""
    return get_save_dir() / filename


def save_state(data: dict[str, Any] | SaveSnapshot) -> Path:
    """Save state data as JSON."""
    if isinstance(data, dict):
        snapshot = SaveSnapshot.model_validate(data)
    else:
        snapshot = data
    path = get_save_path()
    with path.open("w", encoding="utf-8") as f:
        f.write(snapshot.model_dump_json(indent=2))
    return path


def load_state(filename: str = DEFAULT_SAVE_NAME) -> SaveSnapshot | None:
    """Load state data from JSON, or None if not found/invalid."""
    try:
        path = get_save_path(filename)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        return SaveSnapshot.model_validate(raw)
    except Exception:
        return None
