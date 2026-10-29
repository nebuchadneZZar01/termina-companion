"""Planning Agent: builds an ordered, time-boxed plan from relevant objectives.

The agent always asks the configured LLM via structured Pydantic output. It
receives the state summary, retrieved objectives and, on re-planning, the
previous validation feedback. The LLM answers against a permissive draft
schema (``_DraftPlan``) so degenerate windows (e.g. zero-length at Day 3
29:59) parse instead of failing the strict cross-field window check during
invocation.

LLM output is post-processed deterministically: raw draft windows are
sanitized into strict :class:`~app.domain.TimeWindow` objects; step refs,
titles and locations are grounded to the knowledge objectives; duplicate steps
are removed; each step's window is clamped inside its objective's window; and
the authoritative prerequisite chain is rebuilt before validation. The rebuild
keeps the LLM's window only when it fits the chain — after the dependencies,
after the previous step, before the successor's slot — and re-slots it on a
one-hour slot otherwise, so the plan stays chronological and non-overlapping.
"""

from __future__ import annotations

import logging
import time

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.planning_chain import (
    _clamp_windows,
    _dedupe_steps,
    _ground_llm_steps,
    _reconcile_plan,
    dead_for,
)
from app.agents.planning_draft import _DraftPlan, _materialize_plan
from app.data.mock_knowledge import Objective
from app.domain import Plan
from app.llm import get_chat_model, llm_error_hint
from app.progress import report
from app.state import PlanningState
from app.trace import TraceCallback

logger = logging.getLogger(__name__)


class PlanningAgentError(RuntimeError):
    """Raised when the Planning Agent cannot obtain a usable LLM plan."""


def run(state: PlanningState) -> dict:
    """Build an ordered, time-boxed plan with the configured LLM.

    Objectives the clock has already closed are left out of the plan and out of
    the LLM context. When every objective is closed, no LLM call is made at all:
    the run returns an empty plan tagged ``plan_engine="unreachable"``, which the
    Critic turns into an explicit temporal verdict instead of a generic failure.

    args:
        state (PlanningState): the workflow state with player state, goal
        and retrieved objectives.

    returns:
        dict: the generated ``plan``, the untouched LLM ``plan_proposal``
        (before grounding and reconciliation), the incremented
        ``replan_attempts``, ``plan_engine`` (``"llm"`` or
        ``"unreachable"``) and ``plan_model``.

    raises:
        PlanningAgentError: if no model is available, the LLM call fails, or
            neither the LLM nor the deterministic chain yields any step.
    """
    if not state.relevant_objectives:
        logger.error("Planning Agent: no relevant objectives to plan from")
        raise PlanningAgentError(
            "No relevant objectives were found for this goal; nothing to plan."
        )

    dead = dead_for(state)
    live = [obj for obj in state.relevant_objectives if obj.id not in dead]
    if not live:
        logger.warning(
            "Planning Agent: every objective is out of reach at %s; no LLM call",
            state.game_state.time,
        )
        return {
            "plan": Plan(goal=state.goal.description),
            "plan_proposal": None,
            "replan_attempts": state.replan_attempts + 1,
            "plan_engine": "unreachable",
            "plan_model": "",
        }

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
    result = _llm_run(state, model, _live_context(state, live))
    # Keep the untouched proposal: the evaluator compares it with the
    # reconciled plan to measure what the deterministic rebuild had to fix.
    # The post-processing mutates in place, so this must be a deep copy.
    proposal = result.model_copy(deep=True)
    result = _ground_llm_steps(result, state.relevant_objectives)
    result = _dedupe_steps(result)
    result = _clamp_windows(result, state.relevant_objectives, state.game_state.time)
    result = _reconcile_plan(result, state)
    if not result.steps:
        logger.error(
            "Planning Agent: LLM returned an empty plan with no objective chain to rebuild"
        )
        raise PlanningAgentError(
            "LLM returned an empty plan and no objective chain could be rebuilt"
        )
    _log_plan(result)
    return {
        "plan": result,
        "plan_proposal": proposal,
        "replan_attempts": state.replan_attempts + 1,
        "plan_engine": "llm",
        "plan_model": plan_model,
    }


def _live_context(state: PlanningState, live: list[Objective]) -> str:
    """The planner context with the objectives the clock closed left out.

    The Knowledge Agent ships one block per objective plus the supplemental
    evidence tail, so leaving the closed objectives out is a selection, never a
    text edit. A state built without blocks (tests, headless callers) keeps its
    rendered context untouched.

    args:
        state (PlanningState): the workflow state with the retrieved context.
        live (list[Objective]): the objectives still reachable.

    returns:
        str: the structured context for the live objectives, then the evidence.
    """
    if not state.planner_context_blocks:
        return state.retrieved_context
    structured = "\n".join(
        state.planner_context_blocks[obj.id]
        for obj in live
        if obj.id in state.planner_context_blocks
    )
    structured = structured or "No relevant objectives found."
    if not state.planner_context_suffix:
        return structured
    return f"{structured}\n\n{state.planner_context_suffix}"


def _llm_run(state: PlanningState, model, context: str) -> Plan:
    """Ask the LLM for a structured plan, with replan feedback when provided.

    The model answers against the permissive ``_DraftPlan`` schema, so raw
    degenerate windows (e.g. a zero-length window at Day 3 29:59) parse
    instead of failing the cross-field ``end must be after start`` check inside
    ``with_structured_output``. The draft is then materialized into a strict
    :class:`~app.domain.Plan` whose windows are sanitized deterministically.

    args:
        state (PlanningState): the workflow state with goal and context.
        model (BaseChatModel): the configured chat model.
        context (str): the rendered objectives, closed ones already removed.

    returns:
        Plan: the LLM-produced plan.

    raises:
        PlanningAgentError: if invocation fails or the model returns a
            malformed plan. An empty plan is returned as such; the caller
            rebuilds the objective chain before deciding it is unusable.
    """
    feedback = ""
    if state.validation and not state.validation.valid:
        feedback = f"\nPrevious validation feedback:\n{state.validation.feedback}"
    prompt = SystemMessage(
        "You are the Planning Agent of a Zelda temporal planner. Build an ordered, "
        "temporal plan that fulfils the player's goal using only the relevant "
        "objectives below. Each objective is listed as:\n"
        "  [id] Title (Location, [Day D, HH:MM \u2192 Day D, HH:MM]) [requires_quests: ...]\n"
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
        "  - every window stays inside the three-day cycle (Day 1 06:00 to "
        "Day 3 29:59). A game day runs from 06:00 to 05:59 the next morning, "
        "so use hours 24-29 for the night after midnight (e.g. Day 1 26:00 is "
        "Day 1 02:00 (+1)).\n"
        "  - Some objectives require other quests to be completed first (shown as "
        "requires_quests). Do NOT add steps from those other quests — only plan "
        "the objectives listed. The Critic will report missing quest prerequisites.\n"
        "  - Supplemental RAG passages are narrative context only: never use "
        "their times, locations, items or prerequisites to override the "
        "bracketed structured objective fields.\n"
        "  - Player preferences and past episodes below bias style only: never "
        "use them to override bracketed windows, locations, items, masks or "
        "prerequisites.\n"
        "  - title: a short natural-language action phrase, never the id.\n"
        "  - Emit one step for every remaining objective even if required items or "
        "masks are missing or its window has already passed; the Critic validates "
        "feasibility."
        f"{feedback}"
    )
    user = HumanMessage(
        f"Player state:\n{state.state_summary}\n"
        f"Goal: {state.goal.description}\n"
        f"{_memory_context(state)}"
        f"Relevant objectives:\n{context}"
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
        raw = model.with_structured_output(_DraftPlan).invoke(
            [prompt, user], config={"callbacks": [TraceCallback()]}
        )
        plan = None if raw is None else _materialize_plan(raw, state)
    except Exception as exc:
        logger.error("Planning Agent: LLM invocation failed: %s", exc)
        raise PlanningAgentError(f"LLM invocation failed: {exc}{llm_error_hint(exc)}") from exc

    elapsed = time.perf_counter() - started
    if plan is None:
        plan = Plan(goal=state.goal.description)
    if not plan.steps:
        # Weak models (e.g. the Ollama default) can answer with no steps even
        # when the objective chain is feasible. Continue with an empty plan:
        # _reconcile_plan rebuilds the chain deterministically, and run() only
        # fails when that rebuild also yields nothing.
        logger.warning("Planning Agent: LLM returned an empty plan; rebuilding from objectives")
    report(
        {
            "node": "plan",
            "phase": "llm_done",
            "steps": len(plan.steps),
            "seconds": round(elapsed, 1),
        }
    )
    logger.info(
        "Planning Agent [LLM]: raw proposal %d step(s) (%.2fs), replan feedback=%s",
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
    """Log the final, post-processed plan step by step.

    The header makes clear this is the reconciled plan (grounded, deduped,
    clamped and rebuilt against the prerequisite chain), not the LLM's raw
    proposal logged earlier by ``_llm_run``.

    args:
        plan (Plan): the final plan to log.

    returns:
        None: logging only.
    """
    logger.info("Planning Agent: final plan (%d step(s)):", len(plan.steps))
    for i, step in enumerate(plan.steps, 1):
        window = f"{step.window.start} - {step.window.end}"
        items = f" needs={step.requires_items}" if step.requires_items else ""
        logger.info("  %2d. [%s] %s @ %s%s", i, window, step.title, step.location, items)
