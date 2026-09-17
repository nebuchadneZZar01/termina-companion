"""Planning Agent: builds an ordered, time-boxed plan from relevant objectives.

With an LLM configured it produces the :class:`~app.domain.Plan` via structured
Pydantic output, given the state summary, retrieved objectives and (on
re-planning) the previous validation feedback. Otherwise it falls back to the
deterministic slot-filling brain below.

LLM output is post-processed deterministically: step refs, titles and
locations are grounded to the knowledge objectives, duplicate steps are
removed, and each step's window is clamped inside its objective's window so
temporal feasibility never depends on the model (see ``_clamp_windows``).

The rule-based brain still drives the re-planning loop in demo mode: the first
attempt schedules naive one-hour slots from the player's current time (so the
Critic Agent has a real conflict to catch), later attempts schedule sequential
slots clamped inside each objective's window.
"""

from __future__ import annotations

import logging
import time

from langchain_core.messages import HumanMessage, SystemMessage

from app.data.mock_knowledge import Objective
from app.domain import ClockTime, Plan, PlanStep, TimeWindow
from app.llm import get_chat_model
from app.state import PlanningState

_SLOT = 1  # hours per step

logger = logging.getLogger(__name__)


def run(state: PlanningState) -> dict:
    """Build an ordered, time-boxed plan for the player's goal.

    Uses the LLM when configured (grounded against the knowledge base) and
    falls back to the deterministic rule-based brain otherwise.

    args:
        state (PlanningState): the workflow state with player state, goal
        and retrieved objectives.

    returns:
        dict: the generated ``plan``, incremented ``replan_attempts`` and
        ``plan_engine`` ("llm" or "rule-based").
    """
    result: Plan | None = None
    engine = "rule-based"
    model = get_chat_model()
    if model is not None:
        result = _llm_run(state, model)
        if result is not None:
            engine = "llm"
    if result is None:
        result = _rule_based_run(state)
    elif engine == "llm":
        result = _ground_llm_steps(result, state.relevant_objectives)
        result = _dedupe_steps(result)
        result = _clamp_windows(result, state.relevant_objectives)
    _log_plan(result)
    return {"plan": result, "replan_attempts": state.replan_attempts + 1, "plan_engine": engine}


def _llm_run(state: PlanningState, model) -> Plan | None:
    """Ask the LLM for a structured plan, with replan feedback when provided.

    args:
        state (PlanningState): the workflow state with goal and context.
        model (BaseChatModel): the configured chat model.

    returns:
        Plan: the LLM-produced plan, or None on failure/empty output so the
        caller falls back to the rule-based brain.
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
        "  - title: a short natural-language action phrase, never the id."
        f"{feedback}"
    )
    user = HumanMessage(
        f"Player state:\n{state.state_summary}\n"
        f"Goal: {state.goal.description}\n"
        f"Relevant objectives:\n{state.retrieved_context}"
    )
    started = time.perf_counter()
    try:
        plan = model.with_structured_output(Plan).invoke([prompt, user])
    except Exception as exc:
        logger.warning("Planning Agent: LLM path failed, falling back to rule-based: %s", exc)
        return None
    elapsed = time.perf_counter() - started
    if not plan.steps:
        logger.warning("Planning Agent: LLM returned an empty plan, falling back to rule-based")
        return None
    logger.info(
        "Planning Agent [LLM]: %d step(s) (%.2fs), replan feedback=%s",
        len(plan.steps),
        elapsed,
        "yes" if feedback else "no",
    )
    return plan


def _rule_based_run(state: PlanningState) -> Plan:
    """Build a deterministic plan from the retrieved objectives.

    The first attempt is deliberately naive (one-hour slots from now) so the
    Critic has a conflict to catch; later attempts clamp slots inside each
    objective's window, ordered by prerequisites.

    args:
        state (PlanningState): the workflow state with game state and
        relevant objectives.

    returns:
        Plan: a step per objective, ordered by prerequisites.
    """
    ordered = _order_by_prerequisites(state.relevant_objectives)
    naive = state.replan_attempts == 0
    steps: list[PlanStep] = []
    prev_end: ClockTime | None = None
    for index, obj in enumerate(ordered):
        window = (
            _naive_window(state.game_state.time, index)
            if naive
            else _window_inside(obj, prev_end or state.game_state.time)
        )
        steps.append(_to_step(obj, index, window))
        prev_end = window.end
    logger.info(
        "Planning Agent [rule-based]: attempt %d (naive=%s), %d step(s)",
        state.replan_attempts + 1,
        naive,
        len(steps),
    )
    return Plan(goal=state.goal.description, steps=steps)


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


def _to_step(obj: Objective, index: int, window: TimeWindow) -> PlanStep:
    """Convert an objective into a plan step at a given index and window.

    args:
        obj (Objective): the knowledge objective to wrap.
        index (int): step index, used to seed ``depends_on``.
        window (TimeWindow): the scheduled window for this step.

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
        depends_on=list(range(index)),
    )


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


def _naive_window(start: ClockTime, index: int) -> TimeWindow:
    """Build the naive one-hour window for the index-th step.

    args:
        start (ClockTime): the player's current time.
        index (int): step index to offset from the start.

    returns:
        TimeWindow: the naive ``_SLOT``-hour window.
    """
    begin = _add_hours(start, index * _SLOT)
    return TimeWindow(start=begin, end=_add_hours(begin, _SLOT))


def _window_inside(obj: Objective, earliest: ClockTime) -> TimeWindow:
    """Clamp a one-hour slot inside an objective's window, after ``earliest``.

    args:
        obj (Objective): the objective whose window constrains the slot.
        earliest (ClockTime): the earliest the slot may start (e.g. the
        previous step's end).

    returns:
        TimeWindow: a slot no later than the objective's window.
    """
    start = _max_clock(earliest, obj.window.start)
    if _clock(start) >= _clock(obj.window.end):
        start = obj.window.start
    end = min(_add_hours(start, _SLOT), obj.window.end, key=_clock)
    if _clock(end) <= _clock(start):
        end = ClockTime(day=3, hour=23, minute=59)
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
