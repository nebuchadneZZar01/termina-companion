"""Deterministic grounding, clamping and prerequisite-chain reconciliation."""

from __future__ import annotations

import logging

from app.agents.planning_clock import _max_clock, _window_inside
from app.data.mock_knowledge import Objective, build_default_knowledge
from app.domain import ClockTime, Plan, PlanStep, TimeWindow
from app.domain import clock_key as _clock
from app.state import PlanningState

_KB = build_default_knowledge()
# objective id -> (quest id, position in the quest's chain)
_OBJECTIVE_POSITION = {
    obj.id: (quest.id, idx) for quest in _KB.quests for idx, obj in enumerate(quest.objectives)
}

logger = logging.getLogger(__name__)


def _to_step(obj: Objective, window: TimeWindow, prior: list[PlanStep]) -> PlanStep:
    """Convert an objective into a plan step at a given window.

    ``depends_on`` only points at the earlier steps whose objectives are this
    one's prerequisites, never at unrelated steps from other quests.

    args:
        obj (Objective): the knowledge objective to wrap.
        window (TimeWindow): the scheduled window for this step.
        prior (list[PlanStep]): steps built so far, prerequisites first.

    returns:
        PlanStep: the resulting step with the objective's actions and
        item/mask requirements.
    """
    return PlanStep(
        title=obj.title,
        objective_ref=obj.id,
        location=obj.location,
        window=window,
        actions=[obj.description],
        requires_items=obj.requires_items,
        requires_masks=obj.requires_masks,
        depends_on=_depends_on_indices(obj, prior),
    )


def _depends_on_indices(obj: Objective, steps: list[PlanStep]) -> list[int]:
    """Indices of earlier steps whose objectives are ``obj``'s prerequisites.

    Only prerequisites present in the plan count; a prerequisite pruned as
    already owned imposes no dependency. Steps of different quests therefore
    never chain to each other, which keeps the Critic's sequence rule
    meaningful across multi-quest goals.

    args:
        obj (Objective): the objective whose prerequisites matter.
        steps (list[PlanStep]): steps built so far, prerequisites first.

    returns:
        list[int]: the ascending indices of matching prerequisite steps.
    """
    return [i for i, s in enumerate(steps) if s.objective_ref in obj.prerequisites]


# ponytail: heuristic ref-resolver. When the LLM emits a plan whose step also
# fits (location, window) of one known objective, re-point its invented
# objective_ref so the Critic can validate it. Titles and actions are always
# re-pointed to the knowledge base's wording so the user never sees raw
# objective ids or untranslatable free text.
# Ceiling: true semantic matching; upgrade path: exact ids from the prompt /
# a stronger model.
def _ground_llm_steps(plan: Plan, objectives: list[Objective]) -> Plan:
    """Pin each LLM step to its knowledge objective: exact ref, human wording."""
    by_id = {o.id: o for o in objectives}
    for step in plan.steps:
        match = by_id.get(step.objective_ref)
        if match is None:
            match = _match_objective(step, objectives)
        if match is not None:
            step.objective_ref = match.id
            step.title = match.title
            step.location = match.location
            step.actions = [match.description or match.title]
            step.requires_items = match.requires_items
            step.requires_masks = match.requires_masks
    return plan


def _dedupe_steps(plan: Plan) -> Plan:
    """Keep one step per objective; drop later repeats and remap depends_on."""
    seen: set[str] = set()
    kept: list[PlanStep] = []
    old_to_new: dict[int, int] = {}
    for idx, step in enumerate(plan.steps):
        if step.objective_ref and step.objective_ref in seen:
            continue
        if step.objective_ref:
            seen.add(step.objective_ref)
        old_to_new[idx] = len(kept)
        kept.append(step)
    for new_idx, step in enumerate(kept):
        step.depends_on = [
            old_to_new[d] for d in step.depends_on if d in old_to_new and old_to_new[d] < new_idx
        ]
    plan.steps = kept
    return plan


# ponytail: deterministic chain enforcement. The LLM may skip chain objectives,
# keep an "obtain item" step for something the player already owns, or schedule
# steps as whole objective slots that overlap their prerequisites. The
# relevant-objective chain (prerequisites first) is authoritative, so the final
# plan is rebuilt around it: objectives up to the furthest reward the player
# already owns are treated as done, fully-owned provide steps beyond it are
# pruned, missing chain steps are re-inserted with deterministic slots, and a
# kept step keeps the LLM's window only when it fits the chain — after its
# dependencies, after the previous step, before the successor's slot — and is
# re-slotted onto a 1h window otherwise. Ceiling: chain position is inferred
# from owned rewards only, so a finished objective that provides nothing and
# has no owned successor yet is planned again; upgrade path: model completed
# objectives explicitly so chains can start mid-quest even then.
def _reconcile_plan(plan: Plan, state: PlanningState) -> Plan:
    """Rebuild the plan around the authoritative objective chain.

    Every chain objective becomes a step, in prerequisite order. The chain
    starts after the furthest objective whose reward the player already owns,
    so a trade chain never asks for items that were already traded away. On the
    first attempt the LLM's window is kept when it fits the chain — it starts
    after the dependencies and after the previous step, and ends before the
    successor's slot opens — and is re-slotted onto a one-hour slot otherwise.
    On a re-plan every window is re-slotted deterministically. The rebuilt
    plan therefore never overlaps itself and never starts a step before its
    prerequisites are done.

    args:
        plan (Plan): the grounded LLM plan.
        state (PlanningState): the workflow state with game state and the
        retrieved objectives.

    returns:
        Plan: the same plan, pruned of done and owned-provide steps and with
        every remaining chain objective present, ordered by prerequisites and
        timed after its dependencies.
    """
    owned_items = set(state.game_state.inventory)
    owned_masks = set(state.game_state.masks)
    by_ref = {s.objective_ref: s for s in plan.steps}
    floor = _owned_chain_floor(state.relevant_objectives, owned_items, owned_masks)
    ordered = _order_by_prerequisites(state.relevant_objectives)
    chain = [
        obj
        for obj in ordered
        if not _already_done(obj, floor) and not _already_owned(obj, owned_items, owned_masks)
    ]
    if not _requirements_covered(chain, owned_items, owned_masks):
        # The inventory contradicts the inferred chain position (e.g. a later
        # reward is owned but an earlier mask is not). Fall back to pruning
        # only objectives whose own reward is already owned, so the missing
        # requirements can still be acquired by the plan.
        chain = [obj for obj in ordered if not _already_owned(obj, owned_items, owned_masks)]
    steps: list[PlanStep] = []
    prev_end: ClockTime | None = None
    for idx, obj in enumerate(chain):
        dependencies = _depends_on_indices(obj, steps)
        earliest = _max_clock(
            state.game_state.time,
            *(steps[d].window.end for d in dependencies),
        )
        existing = by_ref.get(obj.id)
        floor = _max_clock(earliest, prev_end or state.game_state.time)
        if existing is not None:
            existing.depends_on = dependencies
            if state.replan_attempts > 0:
                existing.window = _window_inside(obj, floor)
            else:
                existing.window = _fit_window(
                    existing.window,
                    obj,
                    chain,
                    idx,
                    earliest,
                    prev_end,
                    state.game_state.time,
                )
            steps.append(existing)
            prev_end = existing.window.end
            continue
        window = _window_inside(obj, floor)
        steps.append(_to_step(obj, window, steps))
        prev_end = window.end
    plan.steps = steps
    return plan


def _fit_window(
    desired: TimeWindow,
    obj: Objective,
    chain: list[Objective],
    idx: int,
    earliest: ClockTime,
    prev_end: ClockTime | None,
    now: ClockTime,
) -> TimeWindow:
    """Keep the LLM's window when it fits the chain, else re-slot it.

    A window fits when it starts no earlier than the dependencies and the
    previous step end, and ends no later than the successor's slot opens, so
    the rebuilt plan stays chronological and non-overlapping.

    args:
        desired (TimeWindow): the LLM's window for this objective.
        obj (Objective): the objective being scheduled.
        chain (list[Objective]): the chain of objectives, in order.
        idx (int): the position of ``obj`` in the chain.
        earliest (ClockTime): the earliest this step may start.
        prev_end (ClockTime | None): the end of the previous chain step.
        now (ClockTime): the player's current time.

    returns:
        TimeWindow: the window to use for this step.
    """
    floor = earliest
    if prev_end is not None:
        floor = _max_clock(floor, prev_end)
    cap = _successor_cap(obj, chain, idx, now)
    fits = _clock(desired.start) >= _clock(floor)
    if cap is not None:
        fits = fits and _clock(desired.end) <= _clock(cap)
    if fits:
        return desired
    return _window_inside(obj, floor)


def _successor_cap(
    obj: Objective,
    chain: list[Objective],
    idx: int,
    now: ClockTime,
) -> ClockTime | None:
    """The latest this step may end so its successors still fit.

    args:
        obj (Objective): the objective being scheduled.
        chain (list[Objective]): the chain of objectives, in order.
        idx (int): the position of ``obj`` in the chain.
        now (ClockTime): the player's current time.

    returns:
        ClockTime | None: the latest allowed end, None when the objective has
        no successor in the chain.
    """
    caps = [
        _max_clock(later.window.start, now)
        for later in chain[idx + 1 :]
        if obj.id in later.prerequisites
    ]
    return min(caps, key=_clock) if caps else None


def _requirements_covered(
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


def _owned_chain_floor(
    objectives: list[Objective], owned_items: set[str], owned_masks: set[str]
) -> dict[str, int]:
    """The furthest objective position per quest whose reward the player owns.

    A linear quest chain hands out its rewards in order, so owning the reward
    of objective N means every objective up to N is done — even the ones that
    provide nothing and the ones whose reward was traded away afterwards.

    args:
        objectives (list[Objective]): objectives to inspect.
        owned_items (set[str]): the player's items.
        owned_masks (set[str]): the player's masks.

    returns:
        dict[str, int]: quest id → highest done objective index, absent when
        the player owns no reward from that quest.
    """
    floor: dict[str, int] = {}
    for obj in objectives:
        position = _OBJECTIVE_POSITION.get(obj.id)
        if position is None or not _already_owned(obj, owned_items, owned_masks):
            continue
        quest_id, idx = position
        floor[quest_id] = max(floor.get(quest_id, -1), idx)
    return floor


def _already_done(obj: Objective, floor: dict[str, int]) -> bool:
    """Whether the objective sits at or before its quest's owned-reward floor.

    args:
        obj (Objective): the objective to test.
        floor (dict[str, int]): quest id → furthest done objective index.

    returns:
        bool: True when the objective is already done, False when it is not or
        its quest is unknown.
    """
    position = _OBJECTIVE_POSITION.get(obj.id)
    if position is None:
        return False
    quest_id, idx = position
    return idx <= floor.get(quest_id, -1)


def _already_owned(obj: Objective, owned_items: set[str], owned_masks: set[str]) -> bool:
    """Whether the player already holds everything the objective provides.

    An objective that only exists to hand over items/masks (e.g. retrieving
    Kafei's letter) is redundant once the player owns them, so it can be
    pruned from the plan without breaking the chain.

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
    return (
        (provides_items or provides_masks)
        and provides_items <= owned_items
        and provides_masks <= owned_masks
    )  # noqa: E501


# ponytail: output guardrail on temporal feasibility. Shrinks LLM windows
# into the objective's slot; assumes objective.window is the authoritative
# temporal constraint (true in the vertical slice). Ceiling: also intersect
# with per-NPC schedules; upgrade when NPC availability differs from the
# objective windows.
def _clamp_windows(plan: Plan, objectives: list[Objective]) -> Plan:
    """Pin each step's window inside its objective's window, deterministically.

    The LLM frequently emits windows that overflow or miss the slot in which
    the objective can happen (e.g. Day 1 for a Day 2 objective). This cuts
    each ``step.window`` to the intersection with its objective's window, so
    trivial time/NPC issues never burn one of the bounded re-plan attempts.
    When the LLM window is fully outside the slot, fall back to a ``_SLOT``
    -hour slot at the objective's window start (``_window_inside``).

    Deliberately out of scope: ordering, ``depends_on``, items and masks — the
    Critic Agent stays authoritative for the plan's semantics. This only
    constrains *where in time* each step may happen.

    args:
        plan (Plan): the grounded, deduped LLM plan.
        objectives (list[Objective]): knowledge objectives to clamp against.

    returns:
        Plan: the same plan, each grounded step's window inside its slot.
    """
    by_id = {o.id: o for o in objectives}
    for step in plan.steps:
        obj = by_id.get(step.objective_ref)
        if obj is None:
            continue
        start = _max_clock(step.window.start, obj.window.start)
        end = min(step.window.end, obj.window.end, key=_clock)
        if _clock(start) >= _clock(end):
            step.window = _window_inside(obj, obj.window.start)
        else:
            step.window = TimeWindow(start=start, end=end)
    return plan


def _match_objective(step: PlanStep, objectives: list[Objective]) -> Objective | None:
    """Resolve a plan step to its matching knowledge objective.

    Tries: unique location + window fit, then id substring overlap, then
    best title keyword overlap.

    args:
        step (PlanStep): the step to resolve.
        objectives (list[Objective]): candidate knowledge objectives.

    returns:
        Objective: the unique best match, or None when ambiguous.
    """
    start, end = _clock(step.window.start), _clock(step.window.end)
    fits = [
        o
        for o in objectives
        if o.location == step.location
        and _clock(o.window.start) <= start < end <= _clock(o.window.end)
    ]
    if len(fits) == 1:
        return fits[0]
    ref = step.objective_ref.lower()
    for o in objectives:
        if ref and (ref in o.id.lower() or o.id.lower() in ref):
            return o
    scored = [
        (o, sum(w.lower() in o.title.lower() for w in step.title.split())) for o in objectives
    ]
    best = [
        o for o, score in scored if score == max((s for _, s in scored), default=0) and score > 0
    ]
    return best[0] if len(best) == 1 else None


def _order_by_prerequisites(objectives: list[Objective]) -> list[Objective]:
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
