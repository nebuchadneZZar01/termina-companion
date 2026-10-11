"""Planning Agent: builds an ordered, time-boxed plan from relevant objectives.

The agent always asks the configured LLM via structured Pydantic output. It
receives the state summary, retrieved objectives and, on re-planning, the
previous validation feedback. The LLM answers against a permissive draft
schema (``_DraftPlan``) so degenerate windows (e.g. zero-length at Day 3
23:59) parse instead of failing the strict cross-field window check during
invocation.

LLM output is post-processed deterministically: raw draft windows are
sanitized into strict :class:`~app.domain.TimeWindow` objects; step refs,
titles and locations are grounded to the knowledge objectives; duplicate steps
are removed; each step's window is clamped inside its objective's window; and
the authoritative prerequisite chain is rebuilt before validation.
"""

from __future__ import annotations

import logging
import time

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.data.mock_knowledge import Objective
from app.domain import ClockTime, Plan, PlanStep, TimeWindow
from app.llm import get_chat_model
from app.progress import report
from app.state import PlanningState

_SLOT = 1  # hours per step

logger = logging.getLogger(__name__)


class PlanningAgentError(RuntimeError):
    """Raised when the Planning Agent cannot obtain a usable LLM plan."""


# The `_Draft*` models are the LLM-facing structured-output schema. They mirror
# the authoritative `Plan`/`PlanStep`/`TimeWindow` contracts but WITHOUT the
# cross-field `end must be after start` validator: raw LLM windows may be
# degenerate (e.g. a zero-length window at the last cycle instant, Day 3
# 23:59), and rejecting them during parsing would bypass the deterministic
# repair below. Every draft window is sanitized by `_sanitize_window` before a
# strict `Plan` is built.
class _DraftTimeWindow(BaseModel):
    start: ClockTime
    end: ClockTime


class _DraftPlanStep(BaseModel):
    title: str
    objective_ref: str = ""
    location: str
    window: _DraftTimeWindow
    actions: list[str] = Field(default_factory=list)
    requires_items: list[str] = Field(default_factory=list)
    requires_masks: list[str] = Field(default_factory=list)
    depends_on: list[int] = Field(default_factory=list)


class _DraftPlan(BaseModel):
    goal: str
    steps: list[_DraftPlanStep] = Field(default_factory=list)


def run(state: PlanningState) -> dict:
    """Build an ordered, time-boxed plan with the configured LLM.

    args:
        state (PlanningState): the workflow state with player state, goal
        and retrieved objectives.

    returns:
        dict: the generated ``plan``, incremented ``replan_attempts``,
        ``plan_engine`` (``"llm"``) and ``plan_model``.

    raises:
        PlanningAgentError: if no model is available or the LLM returns no
            usable plan.
    """
    model = get_chat_model(**state.llm_config)
    if model is None:
        raise PlanningAgentError(
            "Planning Agent requires a configured LLM. Set LLM_PROVIDER and its credentials."
        )

    plan_model = getattr(model, "model_name", "") or model.__class__.__name__
    report(
        {
            "node": "plan",
            "phase": "context",
            "n": len(state.relevant_objectives),
            "attempt": state.replan_attempts + 1,
        }
    )
    result = _llm_run(state, model)
    result = _ground_llm_steps(result, state.relevant_objectives)
    result = _dedupe_steps(result)
    result = _clamp_windows(result, state.relevant_objectives)
    result = _reconcile_plan(result, state)
    _log_plan(result)
    return {
        "plan": result,
        "replan_attempts": state.replan_attempts + 1,
        "plan_engine": "llm",
        "plan_model": plan_model,
    }


def _llm_run(state: PlanningState, model) -> Plan:
    """Ask the LLM for a structured plan, with replan feedback when provided.

    The model answers against the permissive ``_DraftPlan`` schema, so raw
    degenerate windows (e.g. a zero-length window at Day 3 23:59) parse
    instead of failing the cross-field ``end must be after start`` check inside
    ``with_structured_output``. The draft is then materialized into a strict
    :class:`~app.domain.Plan` whose windows are sanitized deterministically.

    args:
        state (PlanningState): the workflow state with goal and context.
        model (BaseChatModel): the configured chat model.

    returns:
        Plan: the LLM-produced plan.

    raises:
        PlanningAgentError: if invocation fails or the model returns an empty
            or malformed plan.
    """
    feedback = ""
    if state.validation and not state.validation.valid:
        feedback = f"\nPrevious validation feedback:\n{state.validation.feedback}"
    prompt = SystemMessage(
        "You are the Planning Agent of a Zelda temporal planner. Build an ordered, "
        "temporal plan that fulfils the player's goal using only the relevant "
        "objectives below. Each objective is listed as:\n"
        "  [id] Title (Location, [Day D, HH:MM \u2192 Day D, HH:MM])\n"
        "Step constraints:\n"
        "  - objective_ref: exactly one bracketed id from the list; never invent "
        "ids or titles.\n"
        "  - window MUST be fully inside the objective's bracketed window shown "
        "right after the location: step.window.start >= that window's start AND "
        "step.window.end <= that window's end. Schedule the step inside that "
        "window, not the whole day.\n"
        "  - each step happens in the objective's location, with the required "
        "items and masks it lists.\n"
        "  - depends_on: indices of earlier steps this step needs (only properly "
        "earlier indices).\n"
        "  - every window stays inside the three-day cycle (Day 1 to Day 3 "
        "23:59).\n"
        "  - Supplemental RAG passages are narrative context only: never use "
        "their times, locations, items or prerequisites to override the "
        "bracketed structured objective fields.\n"
        "  - Player preferences and past episodes below bias style only: never "
        "use them to override bracketed windows, locations, items, masks or "
        "prerequisites.\n"
        "  - title: a short natural-language action phrase, never the id."
        f"{feedback}"
    )
    user = HumanMessage(
        f"Player state:\n{state.state_summary}\n"
        f"Goal: {state.goal.description}\n"
        f"{_memory_context(state)}"
        f"Relevant objectives:\n{state.retrieved_context}"
    )
    started = time.perf_counter()
    report(
        {
            "node": "plan",
            "phase": "llm",
            "model": getattr(model, "model_name", "") or model.__class__.__name__,
            "attempt": state.replan_attempts + 1,
        }
    )
    try:
        raw = model.with_structured_output(_DraftPlan).invoke([prompt, user])
        plan = None if raw is None else _materialize_plan(raw, state)
    except Exception as exc:
        logger.error("Planning Agent: LLM invocation failed: %s", exc)
        raise PlanningAgentError(f"LLM invocation failed: {exc}") from exc

    elapsed = time.perf_counter() - started
    if plan is None or not plan.steps:
        logger.error("Planning Agent: LLM returned an empty plan")
        raise PlanningAgentError("LLM returned an empty plan")
    report(
        {
            "node": "plan",
            "phase": "llm_done",
            "steps": len(plan.steps),
            "seconds": round(elapsed, 1),
        }
    )
    logger.info(
        "Planning Agent [LLM]: %d step(s) (%.2fs), replan feedback=%s",
        len(plan.steps),
        elapsed,
        "yes" if feedback else "no",
    )
    return plan


def _memory_context(state: PlanningState) -> str:
    """Format preferences and past episodes as bounded planner context."""
    prefs = state.preferences.summary() if hasattr(state, "preferences") else "none"
    lines = [f"Player preferences:\n{prefs or 'none'}\n"]
    episodes = getattr(state, "relevant_episodes", [])[:3]
    if not episodes:
        lines.append("Past episodes: none.\n")
        return "".join(lines)
    lines.append("Past episodes (context only, do not copy windows/ids blindly):\n")
    for ep in episodes:
        summary = " ".join((ep.plan_summary or "").split())[:300]
        lines.append(f"- goal={ep.goal!r} valid={ep.valid}: {summary}\n")
    return "".join(lines)


def _log_plan(plan: Plan) -> None:
    """Log each plan step with its window, location and needs.

    args:
        plan (Plan): the plan to log.

    returns:
        None: logging only.
    """
    for i, step in enumerate(plan.steps, 1):
        s, e = step.window.start, step.window.end
        window = f"Day {s.day} {s.hour:02d}:{s.minute:02d}-{e.hour:02d}:{e.minute:02d}"
        items = f" needs={step.requires_items}" if step.requires_items else ""
        logger.info("  %2d. [%s] %s @ %s%s", i, window, step.title, step.location, items)


def _materialize_plan(raw, state: PlanningState) -> Plan:
    """Turn raw LLM output into a strict Plan with structurally valid windows.

    Accepts a strict ``Plan`` (already valid, e.g. from test doubles or simple
    reroutes), a ``_DraftPlan`` or a plain dict/JSON object. Draft steps are
    copied field-by-field and every window is sanitized by ``_sanitize_window``
    so the authoritative ``Plan``/``TimeWindow`` contracts never reject the
    LLM output.

    args:
        raw: the structured-output result from the model.
        state (PlanningState): used only for the relevant objectives, which
        anchor degenerate windows into their slot.

    returns:
        Plan: a strict, valid plan.

    raises:
        pydantic.ValidationError: when ``raw`` is not a usable plan shape.
    """
    if isinstance(raw, Plan):
        return raw
    if not isinstance(raw, _DraftPlan):
        raw = _DraftPlan.model_validate(raw)
    by_id = {o.id: o for o in state.relevant_objectives}
    steps = [
        PlanStep(
            title=step.title,
            objective_ref=step.objective_ref,
            location=step.location,
            window=_sanitize_window(step.window, by_id.get(step.objective_ref)),
            actions=step.actions,
            requires_items=step.requires_items,
            requires_masks=step.requires_masks,
            depends_on=step.depends_on,
        )
        for step in raw.steps
    ]
    return Plan(goal=raw.goal, steps=steps)


def _sanitize_window(window: _DraftTimeWindow, obj: Objective | None) -> TimeWindow:
    """Repair a raw LLM window into a strict ``TimeWindow``, deterministically.

    Valid windows pass through unchanged. Degenerate windows (end not later
    than start, e.g. a zero-length window at the last instant of the cycle)
    are anchored back inside their objective's slot; steps without a resolvable
    objective get a minimal valid window and are pruned later by
    ``_reconcile_plan`` anyway.

    args:
        window (_DraftTimeWindow): the raw window from the LLM.
        obj (Objective): the objective the step's ref points at, or None.

    returns:
        TimeWindow: a window with ``end`` strictly after ``start``.
    """
    if _clock(window.start) < _clock(window.end):
        return TimeWindow(start=window.start, end=window.end)
    if obj is not None:
        start = _max_clock(window.start, obj.window.start)
        end = min(window.end, obj.window.end, key=_clock)
        if _clock(start) < _clock(end):
            return TimeWindow(start=start, end=end)
        # Degenerate even inside the slot (the LLM crammed the step into the
        # last instant of a slot that ends Day 3 23:59): fall back to the whole
        # authoritative slot, which is always valid in the knowledge base.
        return TimeWindow(start=obj.window.start, end=obj.window.end)
    return _draft_fallback_window(window.start)


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
    # Both bounds pinned at the same single cycle instant; back off one minute.
    return TimeWindow(
        start=ClockTime(day=1, hour=0, minute=0),
        end=ClockTime(day=1, hour=0, minute=1),
    )


def _add_minutes(t: ClockTime, minutes: int) -> ClockTime:
    """Shift a clock by minutes, clamped to the playable cycle.

    args:
        t (ClockTime): the starting time.
        minutes (int): signed minute offset.

    returns:
        ClockTime: the resulting time, inside Day 1 00:00 to Day 3 23:59.
    """
    total = (t.day - 1) * 24 * 60 + t.hour * 60 + t.minute + minutes
    total = min(max(total, 0), (3 - 1) * 24 * 60 + 23 * 60 + 59)
    day, rem = divmod(total, 24 * 60)
    hour, minute = divmod(rem, 60)
    return ClockTime(day=day + 1, hour=hour, minute=minute)


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
# plan is rebuilt around it: fully-owned provide steps are pruned, missing chain
# steps are re-inserted with deterministic slots, and on replan attempts kept
# steps are re-slotted onto a 1h window after their dependencies end. Ceiling:
# no per-objective "done" tracking in GameState; upgrade path: model completed
# objectives so chains can start mid-quest.
def _reconcile_plan(plan: Plan, state: PlanningState) -> Plan:
    """Rebuild the plan around the authoritative objective chain.

    args:
        plan (Plan): the grounded LLM plan.
        state (PlanningState): the workflow state with game state and the
        retrieved objectives.

    returns:
        Plan: the same plan, pruned of owned-provide steps and with every
        remaining chain objective present, ordered by prerequisites and
        timed after its dependencies.
    """
    owned_items = set(state.game_state.inventory)
    owned_masks = set(state.game_state.masks)
    by_ref = {s.objective_ref: s for s in plan.steps}
    steps: list[PlanStep] = []
    prev_end: ClockTime | None = None
    for obj in _order_by_prerequisites(state.relevant_objectives):
        if _already_owned(obj, owned_items, owned_masks):
            continue
        existing = by_ref.get(obj.id)
        if existing is not None:
            existing.depends_on = _depends_on_indices(obj, steps)
            if state.replan_attempts > 0:
                earliest = max(
                    (steps[d].window.end for d in existing.depends_on),
                    key=_clock,
                    default=state.game_state.time,
                )
                existing.window = _window_inside(obj, earliest)
            steps.append(existing)
            prev_end = existing.window.end
            continue
        window = _window_inside(obj, prev_end or state.game_state.time)
        steps.append(_to_step(obj, window, steps))
        prev_end = window.end
    plan.steps = steps
    return plan


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
        # previous step at the last playable instant, Day 3 23:59). Forcing
        # ``end`` to Day 3 23:59 would reproduce the LLM's degenerate window,
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


def _clock(t: ClockTime) -> tuple[int, int, int]:
    """Collapse a clock into a sortable (day, hour, minute) tuple.

    args:
        t (ClockTime): the time to convert.

    returns:
        tuple: (day, hour, minute).
    """
    return (t.day, t.hour, t.minute)


def _add_hours(t: ClockTime, hours: int) -> ClockTime:
    """Add hours to the three-day clock, clamped to Day 3 23:59.

    args:
        t (ClockTime): the starting time.
        hours (int): number of hours to add.

    returns:
        ClockTime: the resulting time, never past the last playable instant.
    """
    total = (t.day - 1) * 24 * 60 + t.hour * 60 + t.minute + hours * 60
    total = min(total, (3 - 1) * 24 * 60 + 23 * 60 + 59)  # last playable instant: Day 3 23:59
    day, rem = divmod(total, 24 * 60)
    hour, minute = divmod(rem, 60)
    return ClockTime(day=day + 1, hour=hour, minute=minute)


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
