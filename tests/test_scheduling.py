"""The shared scheduler: which chain objectives fit before the cycle ends."""

from __future__ import annotations

from app.agents.scheduling import (
    already_done,
    already_owned,
    order_by_prerequisites,
    owned_chain_floor,
    requirements_covered,
    schedule_chain,
    select_chain,
)
from app.data.mock_knowledge import Objective
from app.domain import ClockTime, TimeWindow

DAY_START = ClockTime(day=1, hour=6)
ONE_DAY = TimeWindow(start=ClockTime(day=1, hour=6), end=ClockTime(day=1, hour=29))


def _objective(
    id_: str,
    start: int,
    end: int,
    *,
    day: int = 1,
    recurring: bool = False,
    prerequisites: list[str] | None = None,
    provides_items: list[str] | None = None,
    provides_masks: list[str] | None = None,
    requires_masks: list[str] | None = None,
) -> Objective:
    """Build an objective with an hour or a day window.

    args:
        id_ (str): the objective id.
        start (int): the window start hour (6-29).
        end (int): the window end hour (6-29).
        day (int, default 1): the game day both hours belong to.
        recurring (bool, default False): daily availability.
        prerequisites (list[str] | None): prerequisite objective ids.
        provides_items (list[str] | None): items the objective hands over.
        provides_masks (list[str] | None): masks the objective hands over.
        requires_masks (list[str] | None): masks it consumes.

    returns:
        Objective: the synthetic objective.
    """
    return Objective.model_validate(
        {
            "id": id_,
            "title": id_,
            "location": "Q",
            "window": {
                "start": {"day": day, "hour": start},
                "end": {"day": day, "hour": end},
            },
            "recurring": recurring,
            "prerequisites": prerequisites or [],
            "provides_items": provides_items or [],
            "provides_masks": provides_masks or [],
            "requires_masks": requires_masks or [],
        }
    )


def _chain(objectives, *, done=None, dead=None, owned_items=None, owned_masks=None, positions=None):
    """Select a chain with empty progress unless the caller says otherwise."""
    return select_chain(
        objectives,
        owned_items=owned_items or set(),
        owned_masks=owned_masks or set(),
        done_ids=done or set(),
        dead=dead or {},
        positions=positions or {},
    )


def test_chain_follows_prerequisites():
    """A successor comes after its prerequisite, whatever the input order."""
    later = _objective("later", 6, 23, prerequisites=["first"])
    first = _objective("first", 6, 23)
    assert [o.id for o in order_by_prerequisites([later, first])] == ["first", "later"]


def test_done_and_dead_objectives_leave_the_chain():
    """Explicit progress and the clock both prune the chain."""
    a = _objective("a", 6, 23)
    b = _objective("b", 6, 23)
    c = _objective("c", 6, 23)
    chain = _chain([a, b, c], done={"b"}, dead={"c": "a"})
    assert [o.id for o in chain] == ["a"]


def test_an_owned_reward_moves_the_chain_floor():
    """Owning a later reward proves the earlier objectives happened."""
    first = _objective("first", 6, 23, provides_items=["Letter"])
    second = _objective("second", 6, 23, prerequisites=["first"])
    positions = {"first": ("q", 0), "second": ("q", 1)}
    chain = _chain([first, second], owned_items={"Letter"}, positions=positions)
    assert [o.id for o in chain] == ["second"]


def test_the_floor_falls_back_when_requirements_contradict_it():
    """A missing mask keeps the earlier objective in the chain."""
    first = _objective("first", 6, 23, provides_masks=["Deku Mask"])
    reward = _objective("reward", 6, 23, prerequisites=["first"], provides_items=["Reward"])
    locked = _objective("locked", 6, 23, prerequisites=["reward"], requires_masks=["Deku Mask"])
    positions = {"first": ("q", 0), "reward": ("q", 1), "locked": ("q", 2)}
    chain = _chain([first, reward, locked], owned_items={"Reward"}, positions=positions)
    # Owning the reward would put the floor past both earlier objectives, but the
    # later one still needs the mask, so the chain starts at the mask again.
    assert [o.id for o in chain] == ["first", "locked"]


def test_helpers_expose_the_pruning_rules():
    """The floor, the owned test and the requirement test agree with each other."""
    first = _objective("first", 6, 23, provides_items=["Key"])
    positions = {"first": ("q", 0)}
    floor = owned_chain_floor([first], {"Key"}, set(), positions)
    assert floor == {"q": 0}
    assert already_done(first, floor, positions)
    assert already_owned(first, {"Key"}, set())
    assert requirements_covered([first], set(), set())
    assert not requirements_covered(
        [_objective("needs", 6, 23, requires_masks=["Missing"])], set(), set()
    )


def test_schedule_places_the_chain_sequentially():
    """Every step starts after the previous one ends, inside its occurrence."""
    chain = [_objective("a", 6, 23), _objective("b", 6, 23)]
    schedule = schedule_chain(chain, DAY_START)
    assert schedule.dropped == ()
    first, second = schedule.placed
    assert (first.window.start.hour, first.window.end.hour) == (6, 7)
    assert (second.window.start.hour, second.window.end.hour) == (7, 8)


def test_schedule_waits_for_a_prerequisite():
    """A successor never starts before its prerequisite ended."""
    first = _objective("first", 6, 23)
    later = _objective("later", 6, 23, prerequisites=["first"])
    schedule = schedule_chain([first, later], DAY_START)
    assert schedule.placed[1].window.start.hour == schedule.placed[0].window.end.hour


def test_schedule_drops_what_the_cycle_cannot_hold():
    """A chain longer than the time left is split, not silently shortened."""
    chain = [_objective(f"o{i}", 6, 7) for i in range(3)]
    schedule = schedule_chain(chain, DAY_START)
    assert list(schedule.placed_ids) == ["o0"]
    assert schedule.dropped_ids == {"o1", "o2"}
    assert [o.id for o in schedule.dropped] == ["o1", "o2"]


def test_a_dropped_objective_does_not_consume_time():
    """The steps after a dropped one are placed against the last step that fit."""
    chain = [
        _objective("first", 6, 7),
        _objective("impossible", 6, 7),
        _objective("later", 8, 10),
    ]
    schedule = schedule_chain(chain, DAY_START)
    assert [p.objective.id for p in schedule.placed] == ["first", "later"]
    assert schedule.placed[1].window.start.hour == 8


def test_a_recurring_objective_moves_to_a_later_day():
    """Daily availability repeats, so the chain can run past its base window."""
    chain = [_objective(f"o{i}", 6, 29, recurring=True) for i in range(30)]
    schedule = schedule_chain(chain, DAY_START)
    days = {placement.window.start.day for placement in schedule.placed}
    assert days == {1, 2}
    assert schedule.dropped == ()


def test_the_cycle_end_is_a_hard_stop():
    """Nothing fits in the last minutes of Day 3."""
    chain = [_objective("a", 6, 23, recurring=True), _objective("b", 6, 23, recurring=True)]
    late = ClockTime(day=3, hour=29, minute=30)
    schedule = schedule_chain(chain, late)
    assert schedule.placed == ()
    assert schedule.dropped_ids == {"a", "b"}
