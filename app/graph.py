"""LangGraph workflow wiring and the top-level run entrypoint.

Pipeline: Game State -> State Agent -> Knowledge Agent -> Planning Agent
-> Critic/Validator -> Plan (with a bounded re-planning loop).

Run it headlessly with ``python -m app`` or from the UI.
"""

from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from app.agents import critic_agent, knowledge_agent, planning_agent, state_agent
from app.domain import GameState, Goal
from app.state import PlanningState

MAX_PLANNING_ATTEMPTS = 3

logger = logging.getLogger(__name__)


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
    graph.add_node("state", state_agent.run)
    graph.add_node("knowledge", knowledge_agent.run)
    graph.add_node("plan", planning_agent.run)
    graph.add_node("critic", critic_agent.run)

    graph.add_edge(START, "state")
    graph.add_edge("state", "knowledge")
    graph.add_edge("knowledge", "plan")
    graph.add_edge("plan", "critic")
    graph.add_conditional_edges("critic", _route, {"valid": END, "replan": "plan", "give_up": END})
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


def run_pipeline(game_state: GameState, goal: Goal) -> PlanningState:
    """Run the full planning pipeline end to end.

    Convenience wrapper over :func:`build_graph`: invokes the graph with the
    given player state and goal, and re-validates the result.

    args:
        game_state (GameState): the player's current state.
        goal (Goal): what the player wants to achieve.

    returns:
        PlanningState: the final workflow state with plan and validation.
    """
    result = build_graph().invoke(PlanningState(game_state=game_state, goal=goal))
    return PlanningState.model_validate(result)
