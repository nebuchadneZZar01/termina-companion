"""LangGraph workflow wiring and the top-level run entrypoint.

Pipeline: Game State -> State Agent -> Knowledge Agent -> Planning Agent
-> Critic/Validator -> Plan (with a bounded re-planning loop).

Run it headlessly with ``python -m app`` or from the UI.
"""

from __future__ import annotations

import logging
import time

from langgraph.graph import END, START, StateGraph
from opentelemetry.trace import Status, StatusCode

from app.agents import critic_agent, knowledge_agent, memory_agent, planning_agent, state_agent
from app.domain import GameState, Goal
from app.memory.models import PlayerPreferences
from app.memory.store import get_memory_store
from app.progress import report
from app.state import PlanningState
from app.trace import (
    INPUT_VALUE_ATTR,
    SPAN_KIND_ATTR,
    get_tracer,
    pipeline_span,
    record_error,
    record_node,
    set_output,
)

MAX_PLANNING_ATTEMPTS = 3

logger = logging.getLogger(__name__)


def _with_start(name: str, run_node):
    """Wrap a node so it announces its own start on the custom stream.

    The UI needs to know which agent is processing *while* it runs, but
    ``stream_mode="updates"`` only emits when a node completes. Announcing the
    start here keeps the signal out of the agents and works for every node
    without duplicating the graph's routing. The same wrapper opens one
    ``node.*`` span per node (OpenInference ``CHAIN`` kind, explicit status,
    state input and structured output for the backend) and records the
    outcome for the run audit.
    """

    def wrapped(state: PlanningState):
        report({"node": name, "phase": "start"})
        started = time.perf_counter()
        with get_tracer().start_span(
            f"node.{name}",
            attributes={SPAN_KIND_ATTR: "CHAIN", INPUT_VALUE_ATTR: _node_input(state)},
        ) as node_span:
            try:
                result = run_node(state)
            except Exception as exc:
                node_span.set_status(Status(StatusCode.ERROR, str(exc)))
                node_span.record_exception(exc)
                record_node(name, time.perf_counter() - started, "error", str(exc))
                record_error(name, str(exc))
                raise
            node_span.set_status(Status(StatusCode.OK))
            set_output(node_span, _node_output(name, result))
        record_node(name, time.perf_counter() - started, "ok", _node_detail(name, result))
        return result

    return wrapped


def _node_input(state) -> str:
    """Compact goal/state line as the node span input; never fails."""
    try:
        goal = getattr(getattr(state, "goal", None), "description", "")
        gs = state.game_state
        clock = f"day {gs.time.day} {gs.time.hour:02d}:{gs.time.minute:02d}"
        return f"{goal} | {clock} | {gs.location}"
    except Exception:  # noqa: BLE001 - audit input must never break a run
        return ""


def _node_output(name: str, result: dict):
    """Structured node outcome as the node span output payload; never fails."""
    try:
        if name == "state":
            return str(result.get("state_summary", ""))
        if name == "knowledge":
            objectives = result.get("relevant_objectives") or []
            return [
                {"id": getattr(o, "id", ""), "title": getattr(o, "title", "")} for o in objectives
            ]
        if name == "plan":
            plan = result.get("plan")
            if plan is None:
                return ""
            return [
                {"title": s.title, "location": s.location, "window": str(s.window)}
                for s in plan.steps
            ]
        if name == "critic":
            validation = result.get("validation")
            if validation is None:
                return ""
            return {
                "valid": validation.valid,
                "issues": [f"[{i.severity}/{i.kind}] {i.message}" for i in validation.issues],
            }
        if name in {"memory", "memory_store"}:
            episodes = result.get("relevant_episodes") or []
            if episodes:
                return [{"goal": e.goal, "valid": e.valid} for e in episodes]
            return dict(result)
    except Exception:  # noqa: BLE001 - audit output must never break a run
        return ""
    return dict(result)


def _node_detail(name: str, result: dict) -> str:
    """Short human-readable outcome of a node, for the UI timeline."""
    try:
        if name == "state":
            return str(result.get("state_summary", ""))[:80]
        if name == "knowledge":
            objectives = result.get("relevant_objectives") or []
            return f"{len(objectives)} objective(s)"
        if name == "plan":
            plan = result.get("plan")
            return f"{len(plan.steps)} step(s)" if plan else "no plan"
        if name == "critic":
            validation = result.get("validation")
            if validation is None:
                return ""
            n = len(validation.issues)
            return "valid" if validation.valid else f"{n} issue(s)"
        if name in {"memory", "memory_store"}:
            episodes = result.get("relevant_episodes") or []
            return f"{len(episodes)} episode(s)" if episodes else ""
    except Exception:  # noqa: BLE001 - audit detail must never break a run
        return ""
    return ""


def build_graph():
    """Wire the four agents into the compiled LangGraph workflow.

    The graph runs state → knowledge → plan → critic and routes back to the
    planner on a failed validation (see :func:`_route`).

    args:
        (none)

    returns:
        CompiledStateGraph: the compiled LangGraph ready for ``invoke`` /
        ``stream``.
    """
    graph = StateGraph(PlanningState)
    graph.add_node("memory", _with_start("memory", memory_agent.retrieve_run))
    graph.add_node("memory_store", memory_agent.store_run)
    graph.add_node("state", _with_start("state", state_agent.run))
    graph.add_node("knowledge", _with_start("knowledge", knowledge_agent.run))
    graph.add_node("plan", _with_start("plan", planning_agent.run))
    graph.add_node("critic", _with_start("critic", critic_agent.run))

    graph.add_edge(START, "memory")
    graph.add_edge("memory", "state")
    graph.add_edge("state", "knowledge")
    graph.add_edge("knowledge", "plan")
    graph.add_edge("plan", "critic")
    graph.add_conditional_edges(
        "critic", _route, {"valid": "memory_store", "replan": "plan", "give_up": "memory_store"}
    )
    graph.add_edge("memory_store", END)
    return graph.compile()


def _route(state: PlanningState) -> str:
    """Decide the post-critic edge: finish, re-plan, or give up.

    args:
        state (PlanningState): the workflow state with validation results
        and the re-plan counter.

    returns:
        str: "valid" when the plan passes, "replan" when a new attempt is
        allowed, "give_up" when :data:`MAX_PLANNING_ATTEMPTS` was reached.
    """
    if state.validation and state.validation.valid:
        logger.info("Graph: valid plan — done")
        return "valid"
    if state.replan_attempts >= MAX_PLANNING_ATTEMPTS:
        logger.warning("Graph: replan limit reached (%d) — giving up", MAX_PLANNING_ATTEMPTS)
        return "give_up"
    logger.info(
        "Graph: re-planning (attempt %d/%d)", state.replan_attempts + 1, MAX_PLANNING_ATTEMPTS
    )
    return "replan"


def run_pipeline(
    game_state: GameState, goal: Goal, preferences: PlayerPreferences | None = None
) -> PlanningState:
    """Run the full planning pipeline end to end.

    Convenience wrapper over :func:`build_graph`: invokes the graph with the
    given player state and goal, and re-validates the result.

    args:
        game_state (GameState): the player's current state.
        goal (Goal): what the player wants to achieve.
        preferences (PlayerPreferences | None): style hints saved to memory
            before the run; the retrieve node reloads them into state.

    returns:
        PlanningState: the final workflow state with plan and validation.
    """
    if preferences is not None:
        get_memory_store().save_preferences(preferences)
    with pipeline_span(goal.description):
        result = build_graph().invoke(PlanningState(game_state=game_state, goal=goal))
    return PlanningState.model_validate(result)
