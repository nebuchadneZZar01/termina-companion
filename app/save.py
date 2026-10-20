"""Save/load game state snapshots as JSON."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.domain import ClockTime


class SaveSnapshot(BaseModel):
    """Snapshot of UI/game state for save/load."""

    version: int = 1
    day: int = 1
    time: ClockTime
    location: str = "South Clock Town"
    masks: list[str] = Field(default_factory=list)
    inventory: list[str] = Field(default_factory=list)
    quest_progress: list[str] = Field(default_factory=list)
    goal: str = ""


DEFAULT_SAVE_NAME = "last_save.json"


def get_save_dir() -> Path:
    """Return the directory where save files are stored."""
    cache_dir = Path(os.getenv("RAG_QDRANT_PATH", ".cache/termina-companion/qdrant")).parent
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
    path = get_save_path(filename)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        return SaveSnapshot.model_validate(raw)
    except Exception:
        return None
