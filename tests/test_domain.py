import pytest
from pydantic import ValidationError

from app.domain import ClockTime, GameState, Plan, TimeWindow


def test_clock_time_defaults_to_cycle_dawn():
    """ClockTime defaults to Day 1 06:00, the start of the cycle."""
    clock = ClockTime()
    assert clock.day == 1
    assert clock.hour == 6
    assert str(clock) == "Day 1, 06:00"


def test_clock_time_accepts_the_game_day_night_hours():
    """Hours 24-29 are the night after midnight on the same game day."""
    assert ClockTime(hour=24).display_hour == 0
    assert ClockTime(hour=29, minute=59).display_hour == 5
    assert ClockTime(hour=29, minute=59).next_morning is True
    assert str(ClockTime(day=1, hour=26, minute=30)) == "Day 1, 02:30 (+1)"


def test_clock_time_normalizes_display_hours_to_the_same_game_day():
    """Raw 00:00-05:59 input means late night at the end of the same day."""
    assert ClockTime(day=2, hour=2) == ClockTime(day=2, hour=26)
    assert ClockTime(day=1, hour=0).hour == 24
    assert ClockTime(day=1, hour=5, minute=59).hour == 29


def test_clock_time_rejects_hours_outside_the_cycle():
    """The cycle ends at 29:59; 30 is not a valid hour."""
    with pytest.raises(ValidationError):
        ClockTime(hour=30)


def test_clock_time_rejects_minute_60():
    """Minute 60 is out of range."""
    with pytest.raises(ValidationError):
        ClockTime(minute=60)


def test_game_state_defaults_to_empty_owned():
    """GameState defaults to empty inventory, masks and progress."""
    gs = GameState(time=ClockTime(), location="X")
    assert gs.inventory == []
    assert gs.masks == []
    assert gs.quest_progress == {}


def test_time_window_rejects_empty_or_backwards():
    """Empty or backwards windows are rejected."""
    with pytest.raises(ValidationError):
        TimeWindow(start=ClockTime(day=1, hour=10), end=ClockTime(day=1, hour=10))
    with pytest.raises(ValidationError):
        TimeWindow(start=ClockTime(day=2, hour=10), end=ClockTime(day=1, hour=10))


def test_time_window_contains_is_inclusive_of_start_exclusive_of_end():
    """A window contains its start, not its end."""
    window = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    assert window.contains(ClockTime(day=1, hour=8))
    assert window.contains(ClockTime(day=1, hour=8, minute=59))
    assert not window.contains(ClockTime(day=1, hour=9))


def test_plan_serialises():
    """A Plan survives a dump/validate round-trip."""
    plan = Plan(goal="g", steps=[])
    assert plan.model_dump()["goal"] == "g"
    assert Plan.model_validate(plan.model_dump()) == plan
