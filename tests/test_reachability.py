"""Temporal reachability: what the clock has already closed, and its root.

The three days are one finite timeline, so an expired window strands everything
that depended on it. These tests pin the closure over both arrows
(``prerequisites`` and ``requires_quests``), the deterministic root cause, and
the two escape hatches: explicit progress and recurring availability.
"""

from __future__ import annotations

from app.agents.reachability import dead_objectives
from app.data.mock_knowledge import Objective, Quest, build_default_knowledge
from app.domain import ClockTime
from app.mcp.tools import search_quests

_KB = build_default_knowledge()


def _relevant(text: str) -> list[Objective]:
    """Objectives the Knowledge Agent would retrieve for a goal."""
    return [
        Objective.model_validate(item)
        for group in search_quests(text)
        for item in group["objectives"]
    ]


def _load_quest(quest_id: str) -> Quest | None:
    """Resolve a quest from the in-memory knowledge base, like the planner."""
    return next((quest for quest in _KB.quests if quest.id == quest_id), None)


def _dead(text: str, now: ClockTime, **overrides) -> dict[str, str]:
    """Run the closure over the objectives retrieved for ``text``."""
    kwargs = {
        "owned_items": set(),
        "owned_masks": set(),
        "done_quests": set(),
        "done_objectives": set(),
        "load_quest": _load_quest,
    }
    kwargs.update(overrides)
    return dead_objectives(_relevant(text), now, **kwargs)


def test_expired_chain_collapses_to_one_root():
    """By the second day the whole Anju & Kafei chain is gone, under one root.

    The root is the first step of the branch that can no longer happen, so the
    report names the objective the player actually missed.
    """
    dead = _dead("kafei letter", ClockTime(day=2, hour=8))
    assert set(dead) == {
        "ak_get_kafei_mask",
        "ak_get_room_key",
        "ak_talk_to_anju",
        "ak_meet_in_kitchen",
        "ak_post_letter",
        "ak_meet_kafei",
        "ak_deliver_pendant",
        "ak_sakon_hideout",
        "ak_reunite",
    }
    assert set(dead.values()) == {"ak_get_kafei_mask"}


def test_the_same_chain_is_fully_reachable_on_the_first_day():
    """Nothing is dead while the cycle still has room for every window."""
    assert _dead("kafei letter", ClockTime(day=1, hour=6)) == {}


def test_a_recurring_quest_survives_into_the_third_day():
    """Daily availability never expires, so Pamela's chain stays plannable."""
    assert _dead("pamela", ClockTime(day=3, hour=12)) == {}


def test_a_finished_objective_never_reads_as_dead():
    """Owning the reward is proof that the objective happened."""
    dead = _dead("kafei letter", ClockTime(day=2, hour=8), owned_masks={"Kafei's Mask"})
    assert "ak_get_kafei_mask" not in dead
    assert dead["ak_get_room_key"] == "ak_get_room_key"
    assert dead["ak_reunite"] == "ak_get_room_key"


def test_a_declared_objective_never_reads_as_dead():
    """An explicitly completed objective is out of the timeline's reach."""
    dead = _dead(
        "kafei letter",
        ClockTime(day=2, hour=8),
        done_objectives={"ak_get_kafei_mask", "ak_get_room_key"},
    )
    assert "ak_get_room_key" not in dead
    assert dead["ak_talk_to_anju"] == "ak_talk_to_anju"


def test_a_gate_behind_a_live_quest_is_not_dead():
    """A quest that still has an open window keeps its dependants plannable."""
    dead = _dead("mikau memory", ClockTime(day=1, hour=6))
    assert dead == {}


def test_a_gate_behind_a_dead_quest_kills_the_dependant():
    """Once Romani Ranch is gone, the Zora Mask it unlocks is gone too."""
    dead = _dead("mikau memory", ClockTime(day=2, hour=8))
    assert dead["mm_heal_mikau"] == "rr_get_powder_keg"
    assert set(dead.values()) == {"rr_get_powder_keg"}


def test_an_unrelated_quest_keeps_its_own_reachability():
    """One dead branch never strands another quest's objectives."""
    dead = _dead(
        "reunite anju and kafei free pamela's father",
        ClockTime(day=2, hour=8),
    )
    assert "ak_reunite" in dead
    assert not {"pf_find_pamela", "pf_restore_river"} & set(dead)


def test_a_quest_with_every_objective_done_is_not_dead():
    """A fully completed gate quest never reads as dead (risk R7)."""
    romani = next(quest for quest in _KB.quests if quest.id == "romani_ranch")
    dead = _dead(
        "mikau memory",
        ClockTime(day=2, hour=20),
        done_objectives={obj.id for obj in romani.objectives},
    )
    assert "mm_heal_mikau" not in dead


def test_an_unknown_gate_quest_never_reads_as_dead():
    """Missing knowledge must not turn into a false unreachable verdict."""
    dead = _dead("mikau memory", ClockTime(day=2, hour=20), load_quest=lambda _qid: None)
    assert "mm_heal_mikau" not in dead


def test_the_root_cause_is_deterministic():
    """Two equivalent sets pick the same root, whatever their input order."""
    now = ClockTime(day=2, hour=20)
    forward = _dead("mikau memory", now)
    backward = dead_objectives(
        list(reversed(_relevant("mikau memory"))),
        now,
        owned_items=set(),
        owned_masks=set(),
        done_quests=set(),
        done_objectives=set(),
        load_quest=_load_quest,
    )
    assert forward == backward
