"""Memory domain models: player preferences and past planning episodes."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.domain import ClockTime


class PlayerPreferences(BaseModel):
    """How the player likes to play. Style hints, never hard constraints."""

    playstyle: str = ""
    preferred_areas: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    notes: str = ""

    def is_empty(self) -> bool:
        """Whether no preference was ever set."""
        return not (self.playstyle or self.preferred_areas or self.avoid or self.notes)

    def summary(self) -> str:
        """One-line human summary for prompts and the State Agent."""
        parts: list[str] = []
        if self.playstyle:
            parts.append(self.playstyle)
        if self.preferred_areas:
            parts.append(f"prefers {', '.join(self.preferred_areas)}")
        if self.avoid:
            parts.append(f"avoids {', '.join(self.avoid)}")
        if self.notes:
            parts.append(self.notes)
        return "; ".join(parts) or "none"


class Episode(BaseModel):
    """One finished planning run, stored for future retrieval."""

    id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    goal: str
    location: str = ""
    time: ClockTime = Field(default_factory=ClockTime)
    quest_progress: dict[str, str] = Field(default_factory=dict)
    plan_summary: str = ""
    objective_refs: list[str] = Field(default_factory=list)
    valid: bool = True
    issues_count: int = 0
