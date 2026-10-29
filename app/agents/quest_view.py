"""Quest chains read through the MCP tool seam.

The State Agent and the planner need the authoritative quest chains, not only
the objectives the Knowledge Agent retrieved. They read them from the MCP tools
rather than from ``build_default_knowledge()`` so that swapping the tool backend
(a live MCP host, a database) needs no agent change. The view is pure and
cached: the demo data is static for the life of the process.

``app.ui`` is the one deliberate exception — the sidebar and the entity
highlighter need the whole knowledge base (locations, NPCs, events), so the page
reads it directly for display only. Planning never does.
"""

from __future__ import annotations

from functools import lru_cache

from app.data.mock_knowledge import Objective, Quest
from app.mcp.tools import list_quests


@lru_cache(maxsize=1)
def _quests() -> tuple[Quest, ...]:
    """Load every quest once and validate the tool payload into models."""
    return tuple(Quest.model_validate(quest) for quest in list_quests())


def load_quests() -> list[Quest]:
    """Every quest of the game slice, in knowledge order.

    returns:
        list[Quest]: a fresh list of the cached quest models; callers may sort
        or filter it without mutating the cached state.
    """
    return list(_quests())


@lru_cache(maxsize=1)
def quest_index() -> dict[str, Quest]:
    """Quest id to quest lookup.

    returns:
        dict[str, Quest]: the cached index; treat it as read-only.
    """
    return {quest.id: quest for quest in _quests()}


def load_quest(quest_id: str) -> Quest | None:
    """Resolve a quest by id through the cached MCP view.

    args:
        quest_id (str): the quest id to resolve.

    returns:
        Quest | None: the quest, or None when the tools do not know it.
    """
    return quest_index().get(quest_id)


@lru_cache(maxsize=1)
def objective_positions() -> dict[str, tuple[str, int]]:
    """Every objective's quest id and position in that quest's chain.

    returns:
        dict[str, tuple[str, int]]: objective id → ``(quest id, position)``;
        the cached mapping is shared, so treat it as read-only.
    """
    return {
        objective.id: (quest.id, idx)
        for quest in _quests()
        for idx, objective in enumerate(quest.objectives)
    }


def objective_by_id(objective_id: str) -> Objective | None:
    """Resolve an objective across every quest through the cached view.

    args:
        objective_id (str): the objective id to resolve.

    returns:
        Objective | None: the objective, or None when no quest owns it.
    """
    return next(
        (
            objective
            for quest in _quests()
            for objective in quest.objectives
            if objective.id == objective_id
        ),
        None,
    )
