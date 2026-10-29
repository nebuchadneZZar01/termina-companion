"""Which chain objectives still fit: the scheduling decision both agents share.

The planner places the authoritative chain in the three-day timeline; the Critic
must know what that chain contains to complain about a plan that quietly lost a
step. Both therefore take the decision from here: first select the chain from the
retrieved objectives, applying explicit progress, the rewards already owned and
the objectives the clock closed, then place it greedily from the player's clock.

A chain objective that does not fit is *dropped* and said so, never skipped in
silence: the plan omits it and the verdict reports that the cycle cannot hold it.

Deliberately out of scope: the LLM's preferred windows. They are an advisory hint
the planner may honour when they already fit the chain; they never change whether
an objective fits, which is what keeps the two agents in agreement.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.planning_clock import _max_clock, _window_inside
from app.data.mock_knowledge import Objective
from app.domain import ClockTime, TimeWindow

# objective id -> (quest id, position in the quest's chain). Callers supply it:
# the planner reads the knowledge base, the Critic builds it from its MCP view.
Positions = dict[str, tuple[str, int]]


@dataclass(frozen=True)
class Placement:
    """One chain objective placed at a concrete window.

    attributes:
        objective (Objective): the scheduled objective.
        window (TimeWindow): the slot it was placed in.
    """

    objective: Objective
    window: TimeWindow


@dataclass(frozen=True)
class Schedule:
    """The chain split into what fits before the cycle ends and what does not.

    attributes:
        placed (tuple[Placement, ...]): objectives with a slot, chain order.
        dropped (tuple[Objective, ...]): objectives with no slot left before the
            cycle ends, chain order; the plan must omit them and say so.
    """

    placed: tuple[Placement, ...]
    dropped: tuple[Objective, ...]

    @property
    def placed_ids(self) -> set[str]:
        """The objective ids that fit.

        returns:
            set[str]: ids of the placed objectives.
        """
        return {placement.objective.id for placement in self.placed}

    @property
    def dropped_ids(self) -> set[str]:
        """The objective ids that no longer fit.

        returns:
            set[str]: ids of the dropped objectives.
        """
        return {objective.id for objective in self.dropped}


def order_by_prerequisites(objectives: list[Objective]) -> list[Objective]:
    """Topologically order objectives so prerequisites come first.

    Objectives whose prerequisites are outside the given set are treated as
    unconstrained. Degenerate cycles fall back to the remaining order.

    args:
        objectives (list[Objective]): the objectives to order.

    returns:
        list[Objective]: the same objectives, prerequisites first.
    """
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


def already_owned(obj: Objective, owned_items: set[str], owned_masks: set[str]) -> bool:
    """Whether the player already holds everything the objective provides.

    An objective that only exists to hand over items/masks (e.g. retrieving
    Kafei's letter) is redundant once the player owns them, so it can be pruned
    from the plan without breaking the chain.

    args:
        obj (Objective): the objective to test.
        owned_items (set[str]): the player's items.
        owned_masks (set[str]): the player's masks.

    returns:
        bool: True when the objective provides nothing but already-owned
        items/masks.
    """
    provides_items = set(obj.provides_items)
    provides_masks = set(obj.provides_masks)
    return bool(provides_items or provides_masks) and (
        provides_items <= owned_items and provides_masks <= owned_masks
    )


def owned_chain_floor(
    objectives: list[Objective],
    owned_items: set[str],
    owned_masks: set[str],
    positions: Positions,
) -> dict[str, int]:
    """The furthest objective position per quest whose reward the player owns.

    A linear quest chain hands out its rewards in order, so owning the reward
    of objective N means every objective up to N is done — even the ones that
    provide nothing and the ones whose reward was traded away afterwards.

    args:
        objectives (list[Objective]): objectives to inspect.
        owned_items (set[str]): the player's items.
        owned_masks (set[str]): the player's masks.
        positions (Positions): objective id → (quest id, chain position).

    returns:
        dict[str, int]: quest id → highest done objective index, absent when
        the player owns no reward from that quest.
    """
    floor: dict[str, int] = {}
    for obj in objectives:
        position = positions.get(obj.id)
        if position is None or not already_owned(obj, owned_items, owned_masks):
            continue
        quest_id, idx = position
        floor[quest_id] = max(floor.get(quest_id, -1), idx)
    return floor


def already_done(obj: Objective, floor: dict[str, int], positions: Positions) -> bool:
    """Whether the objective sits at or before its quest's owned-reward floor.

    args:
        obj (Objective): the objective to test.
        floor (dict[str, int]): quest id → furthest done objective index.
        positions (Positions): objective id → (quest id, chain position).

    returns:
        bool: True when the objective is already done, False when it is not or
        its quest is unknown.
    """
    position = positions.get(obj.id)
    if position is None:
        return False
    quest_id, idx = position
    return idx <= floor.get(quest_id, -1)


def requirements_covered(
    chain: list[Objective], owned_items: set[str], owned_masks: set[str]
) -> bool:
    """Whether every step's requirements are owned or provided earlier in the chain.

    args:
        chain (list[Objective]): the candidate chain, in plan order.
        owned_items (set[str]): the player's items.
        owned_masks (set[str]): the player's masks.

    returns:
        bool: True when no step needs an item or mask the plan cannot supply.
    """
    available_items = set(owned_items)
    available_masks = set(owned_masks)
    for obj in chain:
        if not set(obj.requires_items) <= available_items:
            return False
        if not set(obj.requires_masks) <= available_masks:
            return False
        available_items.update(obj.provides_items)
        available_masks.update(obj.provides_masks)
    return True


def select_chain(
    objectives: list[Objective],
    *,
    owned_items: set[str],
    owned_masks: set[str],
    done_ids: set[str],
    dead: dict[str, str],
    positions: Positions,
) -> list[Objective]:
    """The objectives the plan must contain, in prerequisite order.

    Progress, owned rewards and the clock prune the retrieved objectives: what
    the player did, what they already hold and what can no longer happen never
    appear in the chain. When the manually entered inventory contradicts that
    position (a later reward owned but an earlier required mask missing), the
    owned-reward floor is dropped so the missing requirements can still be
    acquired, and only explicit progress, closed windows and owned rewards are
    pruned.

    args:
        objectives (list[Objective]): the retrieved objectives.
        owned_items (set[str]): the player's items.
        owned_masks (set[str]): the player's masks.
        done_ids (set[str]): objective ids already completed.
        dead (dict[str, str]): objective id → root, from the reachability closure.
        positions (Positions): objective id → (quest id, chain position).

    returns:
        list[Objective]: the chain to schedule, prerequisites first.
    """
    floor = owned_chain_floor(objectives, owned_items, owned_masks, positions)
    ordered = order_by_prerequisites(objectives)
    chain = [
        obj
        for obj in ordered
        if obj.id not in done_ids
        and obj.id not in dead
        and not already_done(obj, floor, positions)
        and not already_owned(obj, owned_items, owned_masks)
    ]
    if not requirements_covered(chain, owned_items, owned_masks):
        chain = [
            obj
            for obj in ordered
            if obj.id not in done_ids
            and obj.id not in dead
            and not already_owned(obj, owned_items, owned_masks)
        ]
    return chain


def schedule_chain(chain: list[Objective], now: ClockTime) -> Schedule:
    """Place the chain from the player's clock, one slot per objective.

    A step starts no earlier than the player's clock, its placed prerequisites,
    and the previous step, and must fit inside an availability occurrence still
    open at ``now``. A dropped objective does not consume time: the steps after
    it are placed against the last step that did, so the plan never overlaps
    itself and never silently shortens a slot to squeeze an objective in.

    args:
        chain (list[Objective]): the objectives to place, prerequisites first.
        now (ClockTime): the player's clock; nothing is scheduled before.

    returns:
        Schedule: the placed objectives with their windows and the ones the
        cycle no longer has room for.
    """
    placed: list[Placement] = []
    dropped: list[Objective] = []
    prev_end: ClockTime | None = None
    for obj in chain:
        dependencies = [
            slot.window.end for slot in placed if slot.objective.id in obj.prerequisites
        ]
        earliest = _max_clock(now, *dependencies)
        floor = earliest if prev_end is None else _max_clock(earliest, prev_end)
        window = _window_inside(obj, floor, now)
        if window is None:
            dropped.append(obj)
            continue
        placed.append(Placement(objective=obj, window=window))
        prev_end = window.end
    return Schedule(placed=tuple(placed), dropped=tuple(dropped))
