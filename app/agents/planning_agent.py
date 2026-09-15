"""Planning Agent: builds an ordered, time-boxed plan from relevant objectives.

Mock behaviour: the first attempt schedules naive one-hour slots from the
player's current time (ignoring the objectives' windows) so the Critic Agent
has a real conflict to catch and the re-planning loop is exercised. Later
attempts schedule sequential slots clamped inside each objective's window.
"""

from __future__ import annotations

from app.data.mock_knowledge import Objective
from app.domain import ClockTime, Plan, PlanStep, TimeWindow
from app.state import PlanningState

_SLOT = 1  # hours per step


def run(state: PlanningState) -> dict:
    ordered = _order_by_prerequisites(state.relevant_objectives)
    naive = state.replan_attempts == 0
    steps: list[PlanStep] = []
    prev_end: ClockTime | None = None
    for index, obj in enumerate(ordered):
        window = (
            _naive_window(state.game_state.time, index)
            if naive
            else _window_inside(obj, prev_end or state.game_state.time)
        )
        steps.append(_to_step(obj, index, window))
        prev_end = window.end
    plan = Plan(goal=state.goal.description, steps=steps)
    return {"plan": plan, "replan_attempts": state.replan_attempts + 1}


def _to_step(obj: Objective, index: int, window: TimeWindow) -> PlanStep:
    return PlanStep(
        title=obj.title,
        objective_ref=obj.id,
        location=obj.location,
        window=window,
        actions=[obj.description],
        requires_items=obj.requires_items,
        depends_on=list(range(index)),
    )


def _naive_window(start: ClockTime, index: int) -> TimeWindow:
    begin = _add_hours(start, index * _SLOT)
    return TimeWindow(start=begin, end=_add_hours(begin, _SLOT))


def _window_inside(obj: Objective, earliest: ClockTime) -> TimeWindow:
    start = _max_clock(earliest, obj.window.start)
    if _clock(start) >= _clock(obj.window.end):
        start = obj.window.start
    end = min(_add_hours(start, _SLOT), obj.window.end, key=_clock)
    if _clock(end) <= _clock(start):
        end = ClockTime(day=3, hour=23, minute=59)
    return TimeWindow(start=start, end=end)


def _max_clock(*times: ClockTime) -> ClockTime:
    return max(times, key=_clock)


def _clock(t: ClockTime) -> tuple[int, int, int]:
    return (t.day, t.hour, t.minute)


def _add_hours(t: ClockTime, hours: int) -> ClockTime:
    total = (t.day - 1) * 24 * 60 + t.hour * 60 + t.minute + hours * 60
    total = min(total, (3 - 1) * 24 * 60 + 23 * 60 + 59)  # last playable instant: Day 3 23:59
    day, rem = divmod(total, 24 * 60)
    hour, minute = divmod(rem, 60)
    return ClockTime(day=day + 1, hour=hour, minute=minute)


def _order_by_prerequisites(objectives: list[Objective]) -> list[Objective]:
    known = {o.id for o in objectives}
    placed: list[Objective] = []
    remaining = list(objectives)
    while remaining:
        progress = False
        for obj in list(remaining):
            prereqs = [p for p in obj.prerequisites if p in known]
            if all(p in {o.id for o in placed} for p in prereqs):
                placed.append(obj)
                remaining.remove(obj)
                progress = True
        if not progress:
            placed.extend(remaining)
            break
    return placed
