"""Game-knowledge tools shared by the agent layer and the MCP server.

Each function is a plain, synchronous, JSON-serializable callable backed by
``build_default_knowledge()``. ``app.mcp.server`` decorates them as protocol
tools; the Knowledge Agent imports them directly for the in-process path.

Tools are the single seam between the agents and game data: the Knowledge
Agent no longer reaches into the knowledge base itself, so swapping the
underlying source (a live MCP host, RAG, a real database) requires no agent
changes.
"""

from __future__ import annotations

import re

from app.data.mock_knowledge import Objective, build_default_knowledge

_KB = build_default_knowledge()


def search_quests(goal_text: str, quest_progress: dict[str, str] | None = None) -> list[dict]:
    """Find quests whose objectives match the player's goal keywords.

    Returns matched objectives grouped by quest, best matches first.
    Objectives of quests marked "done" are excluded. An empty list means no
    relevant objective: the planner gets nothing grounded rather than an
    unrelated leak from the whole knowledge slice.

    args:
        goal_text (str): the free-text goal description.
        quest_progress (dict[str, str] | None, optional): quest id to status
            map; status "done" hides a whole quest.

    returns:
        list[dict]: one dict per matched quest, with
        ``{"quest_id", "quest_name", "objectives"}`` where each objective is
        its JSON-serialized ``Objective``.
    """
    done = {qid for qid, status in (quest_progress or {}).items() if status == "done"}
    words = set(re.findall(r"[a-z']+", goal_text.lower()))
    scored: list[tuple[int, Objective]] = []
    for quest in _KB.quests:
        if quest.id in done:
            continue
        for obj in quest.objectives:
            score = len(words & set(obj.keywords))
            if score > 0:
                scored.append((score, obj))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    matched = {obj.id for _, obj in scored}
    return [
        {
            "quest_id": quest.id,
            "quest_name": quest.name,
            "objectives": [o.model_dump(mode="json") for o in quest.objectives if o.id in matched],
        }
        for quest in _KB.quests
        if any(o.id in matched for o in quest.objectives)
    ]


def get_npc_schedule(npc_id: str) -> dict:
    """Return an NPC's name, location and availability windows.

    args:
        npc_id (str): the NPC's identifier (e.g. "anju").

    returns:
        dict: ``{"id", "name", "location", "schedule"}`` where schedule lists
        the time windows as readable strings.

    raises:
        ValueError: when the NPC id is unknown.
    """
    npc = _KB.npc(npc_id)
    if npc is None:
        raise ValueError(f"Unknown NPC: {npc_id}")
    return {
        "id": npc.id,
        "name": npc.name,
        "location": npc.location,
        "schedule": [str(w) for w in npc.schedule],
    }


def get_quest_info(quest_id: str) -> dict:
    """Return a quest with all its objectives.

    args:
        quest_id (str): the quest's identifier.

    returns:
        dict: ``{"id", "name", "objectives"}`` with each objective as its
        JSON-serialized ``Objective``.

    raises:
        ValueError: when the quest id is unknown.
    """
    quest = next((q for q in _KB.quests if q.id == quest_id), None)
    if quest is None:
        raise ValueError(f"Unknown quest: {quest_id}")
    return {
        "id": quest.id,
        "name": quest.name,
        "objectives": [o.model_dump(mode="json") for o in quest.objectives],
    }


def get_event(event_id: str) -> dict:
    """Return a scheduled in-world event.

    args:
        event_id (str): the event's identifier.

    returns:
        dict: ``{"id", "name", "location", "window", "description"}`` where
        window is the readable time window string.

    raises:
        ValueError: when the event id is unknown.
    """
    event = _KB.event(event_id)
    if event is None:
        raise ValueError(f"Unknown event: {event_id}")
    return {
        "id": event.id,
        "name": event.name,
        "location": event.location,
        "window": str(event.window),
        "description": event.description,
    }


def get_location(location_id: str) -> dict:
    """Return a named location and the area it belongs to.

    args:
        location_id (str): the location's identifier.

    returns:
        dict: ``{"id", "name", "area"}``.

    raises:
        ValueError: when the location id is unknown.
    """
    loc = next((loc for loc in _KB.locations if loc.id == location_id), None)
    if loc is None:
        raise ValueError(f"Unknown location: {location_id}")
    return {"id": loc.id, "name": loc.name, "area": loc.area}


def check_prerequisites(
    objective_id: str,
    inventory: list[str] | None = None,
    masks: list[str] | None = None,
    quest_progress: dict[str, str] | None = None,
) -> dict:
    """Check whether the player can attempt an objective right now.

    Verifies required items and masks against the player's holdings and the
    objective's prerequisite chain against quest progress (a prerequisite
    objective counts as done when its quest is marked "done").

    args:
        objective_id (str): the objective's identifier.
        inventory (list[str] | None, optional): items the player owns.
        masks (list[str] | None, optional): masks the player owns.
        quest_progress (dict[str, str] | None, optional): quest id to status map.

    returns:
        dict: ``{"objective_id", "met", "missing_items", "missing_masks",
        "unmet_prerequisites"}``.

    raises:
        ValueError: when the objective id is unknown.
    """
    obj = _find_objective(objective_id)
    if obj is None:
        raise ValueError(f"Unknown objective: {objective_id}")
    inventory = inventory or []
    masks = masks or []
    done = {qid for qid, status in (quest_progress or {}).items() if status == "done"}

    def _quest_is_done(prereq_id: str) -> bool:
        for quest in _KB.quests:
            if quest.id in done and any(o.id == prereq_id for o in quest.objectives):
                return True
        return False

    missing_items = [i for i in obj.requires_items if i not in inventory]
    missing_masks = [m for m in obj.requires_masks if m not in masks]
    unmet = [p for p in obj.prerequisites if not _quest_is_done(p)]
    return {
        "objective_id": objective_id,
        "met": not (missing_items or missing_masks or unmet),
        "missing_items": missing_items,
        "missing_masks": missing_masks,
        "unmet_prerequisites": unmet,
    }


def _find_objective(objective_id: str) -> Objective | None:
    """Look up an objective across every quest.

    args:
        objective_id (str): the objective's identifier.

    returns:
        Objective | None: the matching objective, or None when unknown.
    """
    return next((o for quest in _KB.quests for o in quest.objectives if o.id == objective_id), None)
