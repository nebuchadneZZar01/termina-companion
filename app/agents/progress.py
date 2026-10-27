"""Objective-level player progress: the single source of truth for "already done".

Partial quest progress is explicit. The player state carries the ids of the
objectives they have completed, and every agent reads that set instead of
inferring a position along a quest chain. Nothing here assumes a chain shape, so
a branched quest is described exactly as well as a linear one.

The only exception — kept where it already existed — is the reward-based floor
of a trade chain (``planning_chain._owned_chain_floor``): owning an objective's
reward proves the objectives before it happened. That is a game rule, not a
progress inference, and it stays with the planner's chain logic.
"""

from __future__ import annotations

import logging

from app.data.mock_knowledge import KnowledgeBase, Objective, Quest

logger = logging.getLogger(__name__)


def done_objective_ids(
    quests: list[Quest],
    completed_objectives: list[str] | None,
    quest_progress: dict[str, str] | None,
) -> set[str]:
    """Objective ids the player has already completed.

    A quest marked ``done`` counts as every one of its objectives being
    completed; an id in ``completed_objectives`` counts on its own. Unknown ids
    are kept in the result rather than rejected: an id that matches nothing
    simply has no effect, and rejecting it would make the state unloadable after
    a knowledge-base change.

    args:
        quests (list[Quest]): the quests whose chains expand a ``done`` quest.
        completed_objectives (list[str] | None): objective ids recorded as done.
        quest_progress (dict[str, str] | None): quest id to status map; ``done``
            marks a whole quest completed.

    returns:
        set[str]: every objective id that is already done.
    """
    done: set[str] = set(completed_objectives or [])
    done_quests = {qid for qid, status in (quest_progress or {}).items() if status == "done"}
    for quest in quests:
        if quest.id in done_quests:
            done.update(obj.id for obj in quest.objectives)
    return done


def progress_summary(
    quests: list[Quest],
    completed_objectives: list[str] | None,
    quest_progress: dict[str, str] | None,
) -> str:
    """Describe completed quests and how far the in-progress ones have gone.

    Only what the player declared is reported: an objective is "in progress"
    because it is on the quest's chain after the furthest completed objective,
    never because the player happens to stand somewhere.

    args:
        quests (list[Quest]): the game knowledge, for quest and objective names.
        completed_objectives (list[str] | None): objective ids recorded as done.
        quest_progress (dict[str, str] | None): quest id to status map.

    returns:
        str: one line per fact, or "" when the player has no progress at all.
    """
    done_ids = done_objective_ids(quests, completed_objectives, quest_progress)
    done_quests = {qid for qid, status in (quest_progress or {}).items() if status == "done"}
    completed = [quest.name for quest in quests if quest.id in done_quests]
    lines: list[str] = []
    if completed:
        lines.append(f"Completed quests: {', '.join(completed)}.")
    for quest in quests:
        if quest.id in done_quests:
            continue
        furthest = _furthest_done(quest, done_ids)
        if furthest is None:
            continue
        lines.append(f"{quest.name} in progress: {furthest.title} done.")
    return "\n".join(lines)


def _furthest_done(quest: Quest, done_ids: set[str]) -> Objective | None:
    """The last objective of ``quest`` the player has completed, if any.

    args:
        quest (Quest): the quest to inspect.
        done_ids (set[str]): every objective id that is already done.

    returns:
        Objective | None: the furthest completed objective, or None when the
        player has not completed any of the quest's objectives.
    """
    furthest: Objective | None = None
    for obj in quest.objectives:
        if obj.id in done_ids:
            furthest = obj
    return furthest


def objective_labels(kb: KnowledgeBase) -> dict[str, str]:
    """Completed-objective picker options, as objective id → display label.

    One flat widget covers the whole knowledge base; the quest name prefixes the
    label so the chain a step belongs to stays visible, while the stored value
    remains the objective id.

    args:
        kb (KnowledgeBase): the game knowledge.

    returns:
        dict[str, str]: objective id → ``"<Quest>: <Objective title>"``.
    """
    return {obj.id: f"{quest.name}: {obj.title}" for quest in kb.quests for obj in quest.objectives}
