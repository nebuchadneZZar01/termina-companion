"""Curation guards for the game data: which objectives repeat every day.

An objective is ``recurring`` when the player can do it again on any game day —
a place to visit or an NPC to talk to — instead of a dated scene that happens
once per cycle. The flag decides whether a step can ever fall into the past, so
the data is pinned here: a stray flag is a behaviour change, and the golden list
forces a reviewer to see it.
"""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from app.data.mock_knowledge import Objective, build_default_knowledge
from app.domain import ClockTime, TimeWindow

_RECURRING = {
    "dg_get_lens",
    "dg_see_darmani",
    "dg_heal_darmani",
    "dg_get_hot_spring",
    "dg_thaw_elder",
    "dg_learn_lullaby",
    "mm_heal_mikau",
    "mm_talk_band",
    "mm_get_fortress_eggs",
    "mm_get_pinnacle_eggs",
    "mm_deliver_eggs",
    "mm_learn_bossa_nova",
    "mm_play_for_lulu",
    "pf_find_pamela",
    "pf_restore_river",
    "pf_enter_house",
    "pf_free_father",
    "pf_reunite_pamela",
    "dp_get_deku_mask",
    "dp_talk_king",
    "dp_learn_sonata",
    "dp_save_koume",
    "dp_enter_woodfall",
    "dp_rescue_princess",
    "dp_return_princess",
    "dp_butler_race",
    "ss_wake_keeta",
    "ss_open_grave",
    "ss_learn_song_storms",
    "dc_get_moon_tear",
    "dc_get_land_deed",
    "dc_land_to_swamp",
    "dc_swamp_to_mountain",
    "dc_mountain_to_bay",
    "dc_ocean_to_rupee",
}

_ONE_OFF_QUESTS = {"anju_kafei", "bombers", "romani_ranch"}

_DAY_MENTION = re.compile(r"\b(?:First|Second|Third) Day\b|\bDay [123]\b", re.IGNORECASE)


def _objectives() -> dict[str, Objective]:
    """Every shipped objective, keyed by id."""
    return {obj.id: obj for quest in build_default_knowledge().quests for obj in quest.objectives}


def test_recurring_objectives_are_exactly_the_reviewed_set():
    """The recurring set only changes when a reviewer changes this list."""
    recurring = {oid for oid, obj in _objectives().items() if obj.recurring}
    assert recurring == _RECURRING


def test_dated_quests_stay_one_off():
    """Quests built on dated beats never claim daily availability."""
    for quest in build_default_knowledge().quests:
        if quest.id not in _ONE_OFF_QUESTS:
            continue
        assert not [obj.id for obj in quest.objectives if obj.recurring], quest.id


def test_recurring_objectives_do_not_name_a_game_day():
    """Daily availability contradicts a title or description pinned to one day."""
    for oid, obj in _objectives().items():
        if not obj.recurring:
            continue
        assert not _DAY_MENTION.search(f"{obj.title} {obj.description}"), oid


def test_recurring_objective_may_not_be_bound_to_an_event():
    """A recurring objective is a daily availability, not a dated event."""
    window = TimeWindow(start=ClockTime(day=1, hour=6), end=ClockTime(day=1, hour=7))
    with pytest.raises(ValidationError, match="recurring and bound to event"):
        Objective(
            id="bad",
            title="Contradiction",
            location="Nowhere",
            window=window,
            recurring=True,
            event_ref="some_event",
        )


def test_objectives_are_one_off_unless_flagged():
    """The default keeps new data one-off, so the past stays authoritative."""
    window = TimeWindow(start=ClockTime(day=1, hour=6), end=ClockTime(day=1, hour=7))
    obj = Objective(id="plain", title="Plain", location="Nowhere", window=window)
    assert obj.recurring is False


def _minutes(clock: ClockTime) -> int:
    """Monotone minute key over the game-day clock (Day 1 06:00 = 360)."""
    return (clock.day - 1) * 24 * 60 + clock.hour * 60 + clock.minute


def test_every_objective_naming_an_npc_is_possible_in_its_schedule():
    """An NPC-bound objective must overlap an availability window by an hour.

    The Critic requires a plan step to sit inside one of the NPC's schedule
    windows, so an objective whose window never overlaps one can never be
    planned by any engine: the sweep would fail for a data reason and look like
    a planner regression. An objective window wider than the schedule is fine,
    because the planner places the step inside the overlapping part.
    """
    kb = build_default_knowledge()
    npcs = {npc.id: npc for npc in kb.npcs}
    impossible: list[str] = []
    for quest in kb.quests:
        for objective in quest.objectives:
            if not objective.npc_id:
                continue
            npc = npcs.get(objective.npc_id)
            if npc is None:
                impossible.append(f"{objective.id}: unknown NPC {objective.npc_id!r}")
                continue
            usable = max(
                (
                    min(_minutes(window.end), _minutes(objective.window.end))
                    - max(_minutes(window.start), _minutes(objective.window.start))
                    for window in npc.schedule
                ),
                default=0,
            )
            if usable < 60:
                impossible.append(
                    f"{objective.id}: {objective.window} has no hour inside {npc.name}'s schedule"
                )
    assert not impossible, impossible
