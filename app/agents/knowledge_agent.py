"""Knowledge Agent: retrieves game knowledge relevant to the current goal.

Deterministic (rule-based) brain: queries the knowledge base with a keyword
matcher grounded in the player's state and goal, so only objectives that match
the goal reach the planner. The RAG seam (Phase 6) plugs in here later.
"""

from __future__ import annotations

import logging

from app.data.mock_knowledge import build_default_knowledge
from app.state import PlanningState

_KB = build_default_knowledge()

logger = logging.getLogger(__name__)


def run(state: PlanningState) -> dict:
    objectives = _KB.retrieve(state.game_state, state.goal)
    _log_objectives(objectives)
    return {
        "relevant_objectives": objectives,
        "retrieved_context": _format(objectives),
        "knowledge_engine": "rule-based",
    }


def _log_objectives(objectives) -> None:
    logger.info("Knowledge Agent [rule-based]: %d objective(s)", len(objectives))
    for obj in objectives:
        logger.info("  - %s: %s", obj.id, obj.title)


def _format(objectives) -> str:
    lines: list[str] = []
    for obj in objectives:
        lines.append(f"- [{obj.id}] {obj.title} ({obj.location}, {obj.window})")
        npc = _KB.npc(obj.npc_id)
        if npc:
            schedule = ", ".join(str(w) for w in npc.schedule)
            lines.append(f"  - {npc.name}: schedule {schedule}")
        event = _KB.event(obj.event_ref)
        if event:
            lines.append(f"  - event: {event.name} ({event.window})")
    return "\n".join(lines) or "No relevant objectives found."
