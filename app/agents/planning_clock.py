"""Clock arithmetic shared by the planning draft and chain rebuild."""

from __future__ import annotations

import logging

from app.data.mock_knowledge import Objective
from app.domain import ClockTime, TimeWindow
from app.domain import clock_key as _clock

logger = logging.getLogger(__name__)

_SLOT = 1  # hours per step


def _draft_fallback_window(start: ClockTime) -> TimeWindow:
    """Minimal valid window for an ungrounded, degenerate draft window.

    args:
        start (ClockTime): the raw (degenerate) window start.

    returns:
        TimeWindow: a one-minute window at the edge of the raw window.
    """
    later = _add_minutes(start, 1)
    if _clock(later) > _clock(start):
        return TimeWindow(start=start, end=later)
    earlier = _add_minutes(start, -1)
    if _clock(earlier) < _clock(start):
        return TimeWindow(start=earlier, end=start)
    # Both bounds pinned at the same single cycle instant; start at cycle dawn.
    return TimeWindow(
        start=ClockTime(day=1, hour=6, minute=0),
        end=ClockTime(day=1, hour=6, minute=1),
    )


def _offset(t: ClockTime) -> int:
    """Minutes elapsed since the cycle start, Day 1 06:00.

    args:
        t (ClockTime): the time to measure.

    returns:
        int: the signed minute offset from the cycle start.
    """
    return (t.day - 1) * 24 * 60 + (t.hour - 6) * 60 + t.minute


def _add_minutes(t: ClockTime, minutes: int) -> ClockTime:
    """Shift a clock by minutes, clamped to the playable cycle.

    The cycle starts at Day 1 06:00 (offset 0) and ends at Day 3 29:59
    (offset 4319); day rollover happens at 06:00, not midnight.

    args:
        t (ClockTime): the starting time.
        minutes (int): signed minute offset.

    returns:
        ClockTime: the resulting time, inside Day 1 06:00 to Day 3 29:59.
    """
    total = _offset(t) + minutes
    total = min(max(total, 0), 3 * 24 * 60 - 1)
    day, rem = divmod(total, 24 * 60)
    hour, minute = divmod(rem, 60)
    return ClockTime(day=day + 1, hour=hour + 6, minute=minute)


def _window_inside(obj: Objective, earliest: ClockTime, now: ClockTime) -> TimeWindow | None:
    """Clamp a one-hour slot inside an objective's next availability.

    The slot never starts before ``now``: an objective whose window has already
    closed is not available any more, so no slot can host it.

    args:
        obj (Objective): the objective whose availability constrains the slot.
        earliest (ClockTime): the earliest the slot may start (e.g. the
            previous step's end).
        now (ClockTime): the player's current time; nothing is scheduled before.

    returns:
        TimeWindow | None: a slot inside an availability occurrence, always
        with ``end`` strictly after ``start``, or None when the objective has
        no availability left after ``now``.
    """
    for occurrence in occurrences(obj, now):
        start = _max_clock(earliest, now, occurrence.start)
        if _clock(start) >= _clock(occurrence.end):
            continue
        end = min(_add_hours(start, _SLOT), occurrence.end, key=_clock)
        return TimeWindow(start=start, end=end)
    logger.warning("Planning Agent: objective %s has no availability left after %s", obj.id, now)
    return None


def occurrences(obj: Objective, now: ClockTime) -> list[TimeWindow]:
    """The availability windows of an objective still open at ``now``.

    A one-off objective happens once per cycle: its window is its only
    occurrence, and it disappears as soon as ``now`` reaches the window end. A
    recurring objective comes back on every game day at the same time of day, so
    its window repeats on each remaining day — a nightly window keeps running
    past midnight into the same game day's night.

    args:
        obj (Objective): the objective whose availability to compute.
        now (ClockTime): the player's current time.

    returns:
        list[TimeWindow]: the occurrences still open at ``now``, in
        chronological order; empty when the objective is already gone.
    """
    windows = _day_shifted(obj.window) if obj.recurring else [obj.window]
    return [w for w in windows if _clock(w.end) > _clock(now)]


def _day_shifted(window: TimeWindow) -> list[TimeWindow]:
    """Repeat a window on every game day, preserving its time of day.

    args:
        window (TimeWindow): the base availability, on any game day.

    returns:
        list[TimeWindow]: one occurrence per game day of the cycle.
    """
    span = _offset(window.end) - _offset(window.start)
    out: list[TimeWindow] = []
    for day in range(1, 4):
        start = ClockTime(day=day, hour=window.start.hour, minute=window.start.minute)
        end = _add_minutes(start, span)
        if _clock(end) > _clock(start):
            out.append(TimeWindow(start=start, end=end))
    return out


def _max_clock(*times: ClockTime) -> ClockTime:
    """Return the latest clock among the given times.

    args:
        times (ClockTime): one or more clocks to compare.

    returns:
        ClockTime: the latest one.
    """
    return max(times, key=_clock)


def _add_hours(t: ClockTime, hours: int) -> ClockTime:
    """Add hours to the three-day clock, clamped to Day 3 29:59.

    args:
        t (ClockTime): the starting time.
        hours (int): number of hours to add.

    returns:
        ClockTime: the resulting time, never past the last playable instant.
    """
    return _add_minutes(t, hours * 60)
