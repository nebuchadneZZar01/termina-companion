"""Core domain models for Termina Companion.

These are the contracts shared by all agents. No game data lives here;
game knowledge lives in `app.data.mock_knowledge`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Day = Literal[1, 2, 3]


class ClockTime(BaseModel):
    """The three-day cycle clock of Majora's Mask.

    A game day runs from 06:00 to 05:59 the next morning. The internal
    ``hour`` is therefore 6-29: hours 24-29 are the night after midnight
    (24:00 is 00:00, 29:59 is 05:59). Values 0-5 are accepted as a
    convenience and normalized to 24-29 on the same game day.
    """

    day: Day = 1
    hour: int = Field(default=6, ge=6, le=29)
    minute: int = Field(default=0, ge=0, le=59)

    @field_validator("hour", mode="before")
    @classmethod
    def normalize_hour(cls, hour):
        """Map a display hour (00:00-05:59) to the same day's late night.

        args:
            hour: candidate hour, possibly 0-5.

        returns:
            int: 6-29, with 0-5 shifted to 24-29.
        """
        if isinstance(hour, str) and hour.strip().isdigit():
            hour = int(hour.strip())
        if isinstance(hour, int) and 0 <= hour < 6:
            return hour + 24
        return hour

    @property
    def display_hour(self) -> int:
        """The wall-clock hour, 0-23, for user-facing output."""
        return self.hour % 24

    @property
    def next_morning(self) -> bool:
        """Whether this time is after midnight at the end of its game day."""
        return self.hour >= 24

    def __str__(self) -> str:
        """Human-readable clock representation.

        args:
            (none)

        returns:
            str: e.g. "Day 2, 08:00" or "Day 1, 02:30 (+1)".
        """
        suffix = " (+1)" if self.next_morning else ""
        return f"Day {self.day}, {self.display_hour:02d}:{self.minute:02d}{suffix}"


class TimeWindow(BaseModel):
    """A window of availability, e.g. an event or schedule slot."""

    start: ClockTime
    end: ClockTime

    @field_validator("end")
    @classmethod
    def end_after_start(cls, end: ClockTime, info) -> ClockTime:
        """Reject windows whose end is not later than the start.

        args:
            end (ClockTime): candidate end of the window.
            info (ValidationInfo): pydantic context with the parsed start.

        returns:
            ClockTime: the validated end.
        """
        start = info.data["start"]
        if start and not _clock(start) < _clock(end):
            raise ValueError("end must be after start")
        return end

    def __str__(self) -> str:
        """Human-readable window representation.

        args:
            (none)

        returns:
            str: e.g. "[Day 1, 08:00 → Day 1, 09:00]".
        """
        return f"[{self.start} \u2192 {self.end}]"

    def contains(self, t: ClockTime) -> bool:
        """Check whether a clock time falls inside the window.

        The start is inclusive, the end exclusive, over the three-day cycle.

        args:
            t (ClockTime): the time to test.

        returns:
            bool: True when ``start <= t < end``.
        """
        return _clock(self.start) <= _clock(t) < _clock(self.end)


def _clock(t: ClockTime) -> tuple[int, int, int]:
    """Collapse a clock into a sortable (day, hour, minute) tuple.

    args:
        t (ClockTime): the time to convert.

    returns:
        tuple: (day, hour, minute).
    """
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
    requires_masks: list[str] = Field(default_factory=list)
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
        """Summarise the validation outcome as a readable message.

        args:
            (none)

        returns:
            str: "Plan is feasible." on success, otherwise the issues list
            prefixed by "Plan is NOT feasible:".
        """
        if self.valid:
            return "Plan is feasible."
        lines = [f"{i.severity} ({i.kind}): {i.message}" for i in self.issues]
        return "Plan is NOT feasible:\n" + "\n".join(lines)
