"""Core domain models for Termina Companion.

These are the contracts shared by all agents. No game data lives here;
game knowledge lives in `app.data.mock_knowledge`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Day = Literal[1, 2, 3]


class ClockTime(BaseModel):
    """The three-day cycle clock of Majora's Mask."""

    day: Day = 1
    hour: int = Field(default=0, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)

    def __str__(self) -> str:
        return f"Day {self.day}, {self.hour:02d}:{self.minute:02d}"


class TimeWindow(BaseModel):
    """A window of availability, e.g. an event or schedule slot."""

    start: ClockTime
    end: ClockTime

    @field_validator("end")
    @classmethod
    def end_after_start(cls, end: ClockTime, info) -> ClockTime:
        start = info.data["start"]
        if start and not _clock(start) < _clock(end):
            raise ValueError("end must be after start")
        return end

    def contains(self, t: ClockTime) -> bool:
        return _clock(self.start) <= _clock(t) < _clock(self.end)


def _clock(t: ClockTime) -> tuple[int, int, int]:
    return (t.day, t.hour, t.minute)


class GameState(BaseModel):
    """The player's current state: where, when, what they own and did."""

    time: ClockTime
    location: str
    inventory: list[str] = Field(default_factory=list)
    masks: list[str] = Field(default_factory=list)
    quest_progress: dict[str, str] = Field(default_factory=dict)  # quest_id -> objective seen
    notes: str = ""


class Goal(BaseModel):
    """What the player wants to achieve."""

    description: str


class PlanStep(BaseModel):
    """A single actionable step in a temporal plan."""

    title: str
    objective_ref: str = ""  # id of the knowledge objective it fulfils, if any
    location: str
    window: TimeWindow
    actions: list[str] = Field(default_factory=list)
    requires_items: list[str] = Field(default_factory=list)
    depends_on: list[int] = Field(default_factory=list)  # indices of previous steps


class Plan(BaseModel):
    """An ordered, time-boxed plan."""

    goal: str
    steps: list[PlanStep] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    severity: Literal["error", "warning"]
    step_idx: int | None = None
    kind: str  # e.g. "time", "location", "item", "prerequisite"
    message: str


class ValidationResult(BaseModel):
    """Outcome of the Critic/Validator Agent's feasibility check."""

    valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def feedback(self) -> str:
        if self.valid:
            return "Plan is feasible."
        lines = [f"{i.severity} ({i.kind}): {i.message}" for i in self.issues]
        return "Plan is NOT feasible:\n" + "\n".join(lines)
