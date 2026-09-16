"""Knowledge Agent: gathers game knowledge through the MCP tools.

Deterministic (rule-based) brain: calls the MCP tools to search objectives
matching the goal, then pulls the NPC schedules and events the planner needs.
Tools are imported in-process from ``app.mcp.tools``; swapping them for the
protocol client (or another data source) is a drop-in change.
"""

from __future__ import annotations

import logging

from app.data.mock_knowledge import Objective
from app.mcp.tools import get_event, get_npc_schedule, search_quests
from app.state import PlanningState

logger = logging.getLogger(__name__)


def run(state: PlanningState) -> dict:
    """Gather the objectives, NPC schedules and events relevant to the goal.

    args:
        state (PlanningState): the workflow state with the player's game
        state and goal.

    returns:
        dict: ``relevant_objectives``, the formatted ``retrieved_context``
        and ``knowledge_engine``.
    """
    quests = search_quests(state.goal.description, state.game_state.quest_progress)
    objectives = [Objective.model_validate(obj) for quest in quests for obj in quest["objectives"]]
    _log_objectives(objectives)
    npc_schedules = {obj.npc_id: get_npc_schedule(obj.npc_id) for obj in objectives if obj.npc_id}
    events = {obj.event_ref: get_event(obj.event_ref) for obj in objectives if obj.event_ref}
    return {
        "relevant_objectives": objectives,
        "retrieved_context": _format(objectives, npc_schedules, events),
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


def _format(objectives, npc_schedules: dict, events: dict) -> str:
    """Format objectives as a compact text context for the planner.

    Includes id, title, location, window, NPC schedule, event and any
    masks/items needed. NPC schedules and events come from the MCP tools, not
    from direct knowledge base access.

    args:
        objectives (iterable[Objective]): the objectives to format.
        npc_schedules (dict[str, dict]): npc_id to ``get_npc_schedule`` output.
        events (dict[str, dict]): event_id to ``get_event`` output.

    returns:
        str: one block per objective, or "No relevant objectives found."
        when empty.
    """
    lines: list[str] = []
    for obj in objectives:
        lines.append(f"- [{obj.id}] {obj.title} ({obj.location}, {obj.window})")
        npc = npc_schedules.get(obj.npc_id)
        if npc:
            schedule = ", ".join(npc["schedule"])
            lines.append(f"  - {npc['name']}: schedule {schedule}")
        event = events.get(obj.event_ref)
        if event:
            lines.append(f"  - event: {event['name']} ({event['window']})")
        if obj.requires_masks:
            lines.append(f"  - masks needed: {', '.join(obj.requires_masks)}")
        if obj.requires_items:
            lines.append(f"  - items needed: {', '.join(obj.requires_items)}")
    return "\n".join(lines) or "No relevant objectives found."
