"""Planning Agent: builds an ordered, time-boxed plan from relevant objectives.

With an LLM configured it produces the :class:`~app.domain.Plan` via structured
Pydantic output, given the state summary, retrieved objectives and (on
re-planning) the previous validation feedback. Otherwise it falls back to the
deterministic slot-filling brain below.

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
    _log_plan(result)
    return {"plan": result, "replan_attempts": state.replan_attempts + 1, "plan_engine": engine}


def _llm_run(state: PlanningState, model) -> Plan | None:
    feedback = ""
    if state.validation and not state.validation.valid:
        feedback = f"\nPrevious validation feedback:\n{state.validation.feedback}"
    prompt = SystemMessage(
        "You are the Planning Agent of a Zelda temporal planner. Build an ordered, "
        "temporal plan that fulfils the player's goal using only the relevant "
        "objectives below. Schedule each step inside the objective's time window, "
        "in the right location, with the required items. Steps must respect "
        "prerequisites: depends_on lists the indices of earlier steps this step "
        "needs. Set each step's objective_ref to exactly one of the bracketed ids "
        "listed with the objectives and use only those ids. Each step's title "
        "must be a short natural-language action phrase describing the objective, "
        "never the objective id. Every window must be "
        "inside the three-day cycle."
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
    for i, step in enumerate(plan.steps, 1):
        s, e = step.window.start, step.window.end
        window = f"Day {s.day} {s.hour:02d}:{s.minute:02d}-{e.hour:02d}:{e.minute:02d}"
        items = f" needs={step.requires_items}" if step.requires_items else ""
        logger.info("  %2d. [%s] %s @ %s%s", i, window, step.title, step.location, items)


def _to_step(obj: Objective, index: int, window: TimeWindow) -> PlanStep:
    return PlanStep(
        title=obj.title,
        objective_ref=obj.id,
        location=obj.location,
        window=window,
        actions=[obj.description],
        requires_items=obj.requires_items,
        depends_on=list(range(index)),
    )


# ponytail: heuristic ref-resolver. When the LLM emits a plan whose step also
# fits (location, window) of one known objective, re-point its invented
# objective_ref so the Critic can validate it. Titles are always re-pointed to
# the knowledge base's wording so the user never sees raw objective ids.
# Ceiling: true semantic matching; upgrade path: exact ids from the prompt /
# a stronger model.
def _ground_llm_steps(plan: Plan, objectives: list[Objective]) -> Plan:
    """Pin each LLM step to its knowledge objective: exact ref, and human title."""
    by_id = {o.id: o for o in objectives}
    for step in plan.steps:
        match = by_id.get(step.objective_ref)
        if match is None:
            match = _match_objective(step, objectives)
        if match is not None:
            step.objective_ref = match.id
            step.title = match.title
            step.location = match.location
            step.requires_items = match.requires_items
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


def _match_objective(step: PlanStep, objectives: list[Objective]) -> Objective | None:
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
    begin = _add_hours(start, index * _SLOT)
    return TimeWindow(start=begin, end=_add_hours(begin, _SLOT))


def _window_inside(obj: Objective, earliest: ClockTime) -> TimeWindow:
    start = _max_clock(earliest, obj.window.start)
    if _clock(start) >= _clock(obj.window.end):
        start = obj.window.start
    end = min(_add_hours(start, _SLOT), obj.window.end, key=_clock)
    if _clock(end) <= _clock(start):
        end = ClockTime(day=3, hour=23, minute=59)
    return TimeWindow(start=start, end=end)


def _max_clock(*times: ClockTime) -> ClockTime:
    return max(times, key=_clock)


def _clock(t: ClockTime) -> tuple[int, int, int]:
    return (t.day, t.hour, t.minute)


def _add_hours(t: ClockTime, hours: int) -> ClockTime:
    total = (t.day - 1) * 24 * 60 + t.hour * 60 + t.minute + hours * 60
    total = min(total, (3 - 1) * 24 * 60 + 23 * 60 + 59)  # last playable instant: Day 3 23:59
    day, rem = divmod(total, 24 * 60)
    hour, minute = divmod(rem, 60)
    return ClockTime(day=day + 1, hour=hour, minute=minute)


def _order_by_prerequisites(objectives: list[Objective]) -> list[Objective]:
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
