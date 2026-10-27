"""What the three-day clock has already put out of reach.

The three days are a single, finite timeline: an objective's windows are dated
occurrences inside it, not slots that come back tomorrow (unless the objective
is flagged ``recurring``). Once an occurrence is over, everything that needed it
is over too, and no amount of re-planning brings it back — only the Song of Time
restarts the cycle.

This module answers one question for both the planner and the Critic: which
objectives can no longer happen, and what is the root cause of each closed
branch? It is pure and deterministic: the callers inject the quest lookup, so
the planner reads the in-memory knowledge base while the Critic stays behind its
MCP-backed view.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.agents.planning_clock import _max_clock, occurrences
from app.data.mock_knowledge import Objective, Quest
from app.domain import ClockTime
from app.domain import clock_key as _clock

logger = logging.getLogger(__name__)


def dead_objectives(
    objectives: list[Objective],
    now: ClockTime,
    *,
    owned_items: set[str],
    owned_masks: set[str],
    done_quests: set[str],
    done_objectives: set[str],
    load_quest: Callable[[str], Quest | None],
) -> dict[str, str]:
    """Map every objective that can no longer happen to its root cause.

    The closure runs over both arrows that can strand an objective: its
    ``prerequisites`` inside a quest, and the ``requires_quests`` gate between
    quests. A branch dies when its window has closed, when a prerequisite is
    already dead, when the quest it is gated behind can no longer be completed,
    or when its prerequisite cannot even start before the branch's window ends.
    Quests unrelated to a dead branch keep their own objectives.

    An objective the player already completed, or whose reward they already
    hold, is never dead: it needs to happen no more. A quest with no unsatisfied
    objective left is never dead either, so a fully completed quest never
    strands the objectives gated behind it.

    Only the objectives passed in are reported; the objectives of a gated quest
    are loaded and evaluated so the gate can be decided, but they are not part
    of the result.

    args:
        objectives (list[Objective]): the objectives under consideration, e.g.
            the plan's relevant objectives.
        now (ClockTime): the player's current time; nothing earlier is reachable.
        owned_items (set[str]): the player's items.
        owned_masks (set[str]): the player's masks.
        done_quests (set[str]): quest ids marked completed.
        done_objectives (set[str]): objective ids already completed, with done
            quests expanded.
        load_quest (Callable[[str], Quest | None]): resolves a gated quest; None
            when the quest is unknown, which never reads as dead.

    returns:
        dict[str, str]: objective id → id of the root objective that closed the
        branch. Several objectives of the same branch share one root, so callers
        can report one issue per dead chain.
    """
    candidates = {obj.id for obj in objectives}
    by_id: dict[str, Objective] = {obj.id: obj for obj in objectives}
    quests = _gated_quests(objectives, by_id, done_quests, load_quest)
    dead: dict[str, str] = {}

    def satisfied(obj: Objective) -> bool:
        return _is_satisfied(obj, done_objectives, owned_items, owned_masks)

    def next_start(obj: Objective) -> ClockTime | None:
        open_windows = occurrences(obj, now)
        return open_windows[0].start if open_windows else None

    def root_of(roots: list[str]) -> str:
        """The earliest-expiring root, with the objective id as tie-break."""
        return min(roots, key=lambda ref: (_clock(by_id[ref].window.end), ref))

    def quest_dead(quest_id: str) -> bool:
        if quest_id in done_quests:
            return False
        quest = quests.get(quest_id)
        if quest is None:
            return False
        unsatisfied = [obj for obj in quest.objectives if not satisfied(obj)]
        return bool(unsatisfied) and all(obj.id in dead for obj in unsatisfied)

    def root_cause(obj_id: str, obj: Objective) -> str | None:
        """The root that closed this objective, or None while it is reachable.

        A dead prerequisite is the root cause even when the objective's own
        window has also closed: the objective was already impossible when it
        expired, so the branch is reported from the step the player actually
        missed first.
        """
        prereq_roots = [dead[ref] for ref in obj.prerequisites if ref in dead]
        if prereq_roots:
            return root_of(prereq_roots)
        gate_roots = [
            dead[gated.id]
            for quest_id in obj.requires_quests
            if quest_dead(quest_id)
            for gated in quests[quest_id].objectives
            if gated.id in dead
        ]
        if gate_roots:
            return root_of(gate_roots)
        if next_start(obj) is None:
            return obj_id
        starts = [
            start
            for start in (next_start(by_id[ref]) for ref in obj.prerequisites if ref in by_id)
            if start is not None
        ]
        if not _has_slot_after(obj, _max_clock(now, *starts), now):
            return obj_id
        return None

    for _round in range(len(by_id) + 1):
        updated = dict(dead)
        for obj_id, obj in by_id.items():
            if satisfied(obj):
                continue
            root = root_cause(obj_id, obj)
            if root is not None:
                updated[obj_id] = root
        if updated == dead:
            break
        dead = updated
    else:
        # Degenerate prerequisite cycle: no fixpoint exists, so every dead
        # objective reports the same deterministic root instead.
        if dead:
            root = root_of(list(dead.values()))
            dead = {obj_id: root for obj_id in dead}
    return {obj_id: root for obj_id, root in dead.items() if obj_id in candidates}


def _gated_quests(
    objectives: list[Objective],
    by_id: dict[str, Objective],
    done_quests: set[str],
    load_quest: Callable[[str], Quest | None],
) -> dict[str, Quest]:
    """Load every quest reached through ``requires_quests``, transitively.

    The objectives of those quests join ``by_id`` so the same closure decides
    whether the gate can still be satisfied. A completed quest is not loaded: it
    can never be dead.

    args:
        objectives (list[Objective]): the objectives under consideration.
        by_id (dict[str, Objective]): the working set, extended in place.
        done_quests (set[str]): quest ids marked completed.
        load_quest (Callable[[str], Quest | None]): resolves a quest by id.

    returns:
        dict[str, Quest]: the loaded gated quests, by id.
    """
    quests: dict[str, Quest] = {}
    pending = [quest_id for obj in objectives for quest_id in obj.requires_quests]
    while pending:
        quest_id = pending.pop()
        if quest_id in quests or quest_id in done_quests:
            continue
        quest = load_quest(quest_id)
        if quest is None:
            continue
        quests[quest_id] = quest
        for obj in quest.objectives:
            by_id.setdefault(obj.id, obj)
            pending.extend(obj.requires_quests)
    return quests


def _is_satisfied(
    obj: Objective,
    done_objectives: set[str],
    owned_items: set[str],
    owned_masks: set[str],
) -> bool:
    """Whether the player no longer needs the objective to happen.

    An explicit completion counts, and so does already holding everything the
    objective hands over — the trade chains give their rewards in order, so the
    reward is proof enough that the objective happened.

    args:
        obj (Objective): the objective to test.
        done_objectives (set[str]): completed objective ids, quests expanded.
        owned_items (set[str]): the player's items.
        owned_masks (set[str]): the player's masks.

    returns:
        bool: True when the objective does not need to be planned.
    """
    if obj.id in done_objectives:
        return True
    provides_items = set(obj.provides_items)
    provides_masks = set(obj.provides_masks)
    return (
        bool(provides_items or provides_masks)
        and provides_items <= owned_items
        and provides_masks <= owned_masks
    )


def _has_slot_after(obj: Objective, floor: ClockTime, now: ClockTime) -> bool:
    """Whether any open occurrence of ``obj`` extends past ``floor``.

    A step must start after its prerequisites can begin, so an objective whose
    availability ends before that floor has no room left. The floor is built
    from the prerequisites' first possible start, a lower bound on their end, so
    this can only declare unreachable what is truly unreachable.

    args:
        obj (Objective): the objective to test.
        floor (ClockTime): the earliest instant a step could start.
        now (ClockTime): the player's current time.

    returns:
        bool: True when at least one occurrence still has room after ``floor``.
    """
    return any(_clock(window.end) > _clock(floor) for window in occurrences(obj, now))
