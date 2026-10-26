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
    total = (t.day - 1) * 24 * 60 + (t.hour - 6) * 60 + t.minute + minutes
    total = min(max(total, 0), 3 * 24 * 60 - 1)
    day, rem = divmod(total, 24 * 60)
    hour, minute = divmod(rem, 60)
    return ClockTime(day=day + 1, hour=hour + 6, minute=minute)


def _window_inside(obj: Objective, earliest: ClockTime) -> TimeWindow:
    """Clamp a one-hour slot inside an objective's window, after ``earliest``.

    args:
        obj (Objective): the objective whose window constrains the slot.
        earliest (ClockTime): the earliest the slot may start (e.g. the
        previous step's end).

    returns:
        TimeWindow: a slot no later than the objective's window, always with
        ``end`` strictly after ``start``.
    """
    start = _max_clock(earliest, obj.window.start)
    if _clock(start) >= _clock(obj.window.end):
        start = obj.window.start
    end = min(_add_hours(start, _SLOT), obj.window.end, key=_clock)
    if _clock(end) <= _clock(start):
        # The slot is too short for a whole hour (e.g. the LLM anchored the
        # previous step at the last playable instant, Day 3 29:59). Forcing
        # ``end`` to Day 3 29:59 would reproduce the LLM's degenerate window,
        # so pin the whole authoritative slot instead.
        if _clock(obj.window.start) < _clock(obj.window.end):
            return TimeWindow(start=obj.window.start, end=obj.window.end)
        logger.warning(
            "Planning Agent: objective %s has a zero-length slot %s; no step can fit inside it",
            obj.id,
            obj.window,
        )
        return _draft_fallback_window(obj.window.start)
    return TimeWindow(start=start, end=end)


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
