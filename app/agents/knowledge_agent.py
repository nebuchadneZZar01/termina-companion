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
    """Retrieve relevant objectives for the player's goal.

    args:
        state (PlanningState): the workflow state with the player's game
        state and goal.

    returns:
        dict: ``relevant_objectives``, the formatted ``retrieved_context``
        and ``knowledge_engine``.
    """
    objectives = _KB.retrieve(state.game_state, state.goal)
    _log_objectives(objectives)
    return {
        "relevant_objectives": objectives,
        "retrieved_context": _format(objectives),
        "knowledge_engine": "rule-based",
    }


def _log_objectives(objectives) -> None:
    """Log the retrieved objectives at INFO level.

    args:
        objectives (iterable[Objective]): objectives to log.

    returns:
        None: logging only.
    """
    logger.info("Knowledge Agent [rule-based]: %d objective(s)", len(objectives))
    for obj in objectives:
        logger.info("  - %s: %s", obj.id, obj.title)


def _format(objectives) -> str:
    """Format objectives as a compact text context for the planner.

    Includes id, title, location, window, NPC schedule, event and any
    masks/items needed.

    args:
        objectives (iterable[Objective]): the objectives to format.

    returns:
        str: one block per objective, or "No relevant objectives found."
        when empty.
    """
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
        if obj.requires_masks:
            lines.append(f"  - masks needed: {', '.join(obj.requires_masks)}")
        if obj.requires_items:
            lines.append(f"  - items needed: {', '.join(obj.requires_items)}")
    return "\n".join(lines) or "No relevant objectives found."
