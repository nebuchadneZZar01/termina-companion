import pytest
from pydantic import ValidationError

from app.domain import ClockTime, GameState, Plan, TimeWindow


def test_clock_time_defaults():
    assert ClockTime().day == 1


def test_clock_time_rejects_hour_24():
    with pytest.raises(ValidationError):
        ClockTime(hour=24)


def test_clock_time_rejects_minute_60():
    with pytest.raises(ValidationError):
        ClockTime(minute=60)


def test_game_state_defaults_to_empty_owned():
    gs = GameState(time=ClockTime(), location="X")
    assert gs.inventory == []
    assert gs.masks == []
    assert gs.quest_progress == {}


def test_time_window_rejects_empty_or_backwards():
    with pytest.raises(ValidationError):
        TimeWindow(start=ClockTime(day=1, hour=10), end=ClockTime(day=1, hour=10))
    with pytest.raises(ValidationError):
        TimeWindow(start=ClockTime(day=2, hour=10), end=ClockTime(day=1, hour=10))


def test_time_window_contains_is_inclusive_of_start_exclusive_of_end():
    window = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    assert window.contains(ClockTime(day=1, hour=8))
    assert window.contains(ClockTime(day=1, hour=8, minute=59))
    assert not window.contains(ClockTime(day=1, hour=9))


def test_plan_serialises():
    plan = Plan(goal="g", steps=[])
    assert plan.model_dump()["goal"] == "g"
    assert Plan.model_validate(plan.model_dump()) == plan
