"""Deterministic grounding, clamping and prerequisite-chain reconciliation."""

from __future__ import annotations

import logging

from app.agents.planning_clock import _max_clock, _window_inside, occurrences
from app.agents.progress import done_objective_ids
from app.agents.reachability import dead_objectives
from app.agents.scheduling import schedule_chain, select_chain
from app.data.mock_knowledge import Objective, Quest, build_default_knowledge
from app.domain import ClockTime, Plan, PlanStep, TimeWindow
from app.domain import clock_key as _clock
from app.state import PlanningState

_KB = build_default_knowledge()
# objective id -> (quest id, position in the quest's chain)
_OBJECTIVE_POSITION = {
    obj.id: (quest.id, idx) for quest in _KB.quests for idx, obj in enumerate(quest.objectives)
}

logger = logging.getLogger(__name__)


def _load_quest(quest_id: str) -> Quest | None:
    """Resolve a quest from the in-memory knowledge base.

    args:
        quest_id (str): the quest id to resolve.

    returns:
        Quest | None: the quest, or None when the knowledge base does not know it.
    """
    return next((quest for quest in _KB.quests if quest.id == quest_id), None)


def dead_for(state: PlanningState) -> dict[str, str]:
    """Objectives the clock has already closed, with their root cause.

    The player's progress is read the same way everywhere: explicit completed
    objectives, quests marked done, and the rewards already held.

    args:
        state (PlanningState): the workflow state with the game state and the
            retrieved objectives.

    returns:
        dict[str, str]: objective id → root objective id, empty when every
        objective is still reachable.
    """
    gs = state.game_state
    return dead_objectives(
        state.relevant_objectives,
        gs.time,
        owned_items=set(gs.inventory),
        owned_masks=set(gs.masks),
        done_quests={qid for qid, status in gs.quest_progress.items() if status == "done"},
        done_objectives=done_objective_ids(_KB.quests, gs.completed_objectives, gs.quest_progress),
        load_quest=_load_quest,
    )


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
    starts after the furthest objective whose reward the player already owns and
    never contains an objective the player declared completed, so a trade chain
    never asks for items that were already traded away. On the first attempt the
    LLM's window is kept when it fits the chain — it starts after the
    dependencies and after the previous step, and ends before the successor's
    slot opens — and is re-slotted onto a one-hour slot otherwise. On a re-plan
    every window is re-slotted deterministically. The rebuilt plan therefore
    never overlaps itself and never starts a step before its prerequisites are
    done.

    args:
        plan (Plan): the grounded LLM plan.
        state (PlanningState): the workflow state with game state and the
        retrieved objectives.

    returns:
        Plan: the same plan, pruned of explicit done, reward-floor done and
        owned-provide steps and with every remaining chain objective present,
        ordered by prerequisites and timed after its dependencies.
    """
    owned_items = set(state.game_state.inventory)
    owned_masks = set(state.game_state.masks)
    done_ids = done_objective_ids(
        _KB.quests,
        state.game_state.completed_objectives,
        state.game_state.quest_progress,
    )
    by_ref = {s.objective_ref: s for s in plan.steps}
    dead = dead_for(state)
    now = state.game_state.time
    chain = select_chain(
        state.relevant_objectives,
        owned_items=owned_items,
        owned_masks=owned_masks,
        done_ids=done_ids,
        dead=dead,
        positions=_OBJECTIVE_POSITION,
    )
    # The scheduler decides what fits; the LLM only suggests when. A dropped
    # objective has no slot left before the cycle ends, so no window of its own.
    slots = {p.objective.id: p.window for p in schedule_chain(chain, now).placed}
    steps: list[PlanStep] = []
    prev_end: ClockTime | None = None
    for idx, obj in enumerate(chain):
        slot = slots.get(obj.id)
        if slot is None:
            logger.warning("Planning Agent: %s does not fit before the cycle ends", obj.id)
            continue
        dependencies = _depends_on_indices(obj, steps)
        earliest = _max_clock(
            now,
            *(steps[d].window.end for d in dependencies),
        )
        existing = by_ref.get(obj.id)
        window = slot
        if existing is not None:
            existing.depends_on = dependencies
            if state.replan_attempts <= 0:
                fitted = _fit_window(
                    existing.window,
                    obj,
                    chain,
                    idx,
                    earliest,
                    prev_end,
                    now,
                )
                window = slot if fitted is None else fitted
            existing.window = window
            steps.append(existing)
            prev_end = window.end
            continue
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
) -> TimeWindow | None:
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
        TimeWindow | None: the window to use for this step, or None when the
        objective has no availability left after ``now``.
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
    return _window_inside(obj, floor, now)


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
        no successor in the chain or no successor is still available.
    """
    caps = [
        open_windows[0].start
        for later in chain[idx + 1 :]
        if obj.id in later.prerequisites
        for open_windows in [occurrences(later, now)]
        if open_windows
    ]
    return min(caps, key=_clock) if caps else None


# ponytail: output guardrail on temporal feasibility. Shrinks LLM windows
# into an availability occurrence of the objective; treats objective.window as
# the authoritative temporal constraint (true in the vertical slice). Ceiling:
# also intersect with per-NPC schedules; upgrade when NPC availability differs
# from the objective windows.
def _clamp_windows(plan: Plan, objectives: list[Objective], now: ClockTime) -> Plan:
    """Pin each step inside an availability occurrence, dropping closed steps.

    The LLM frequently emits windows that overflow or miss the slot in which
    the objective can happen (e.g. Day 1 for a Day 3 objective), or windows in
    the past. This cuts each ``step.window`` to the intersection with the
    objective's next open occurrence, never before ``now``, so trivial
    time/NPC issues never burn one of the bounded re-plan attempts, and no step
    is ever scheduled at an hour that has already gone by.

    A step whose objective has no availability left is removed instead of
    being clamped: there is no future hour in which it can happen.

    Deliberately out of scope: ordering, ``depends_on``, items and masks — the
    Critic Agent stays authoritative for the plan's semantics. This only
    constrains *where in time* each step may happen.

    args:
        plan (Plan): the grounded, deduped LLM plan.
        objectives (list[Objective]): knowledge objectives to clamp against.
        now (ClockTime): the player's current time; nothing is scheduled before.

    returns:
        Plan: the same plan without its closed steps, each remaining step's
        window inside an occurrence still open at ``now``.
    """
    by_id = {o.id: o for o in objectives}
    kept: list[PlanStep] = []
    old_to_new: dict[int, int] = {}
    for idx, step in enumerate(plan.steps):
        obj = by_id.get(step.objective_ref)
        if obj is not None:
            window = _clamp_to_occurrence(step.window, obj, now)
            if window is None:
                logger.warning(
                    "Planning Agent: dropping step %s: no availability left after %s",
                    obj.id,
                    now,
                )
                continue
            step.window = window
        old_to_new[idx] = len(kept)
        kept.append(step)
    for new_idx, step in enumerate(kept):
        step.depends_on = [
            old_to_new[d] for d in step.depends_on if d in old_to_new and old_to_new[d] < new_idx
        ]
    plan.steps = kept
    return plan


def _clamp_to_occurrence(desired: TimeWindow, obj: Objective, now: ClockTime) -> TimeWindow | None:
    """Cut a desired window into the objective's next open occurrence.

    A window that misses every open occurrence (e.g. the LLM kept Day 1 for a
    daily availability while the player is on Day 2) is re-slotted onto the next
    available hour, so the plan stays feasible without another LLM call.

    args:
        desired (TimeWindow): the LLM's window for the step.
        obj (Objective): the objective the step is grounded to.
        now (ClockTime): the player's current time; nothing is scheduled before.

    returns:
        TimeWindow | None: the clamped window, or None when the objective has
        no availability left after ``now``.
    """
    open_windows = occurrences(obj, now)
    for occurrence in open_windows:
        start = _max_clock(desired.start, occurrence.start, now)
        end = min(desired.end, occurrence.end, key=_clock)
        if _clock(start) < _clock(end):
            return TimeWindow(start=start, end=end)
    if open_windows:
        return _window_inside(obj, now, now)
    return None


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
