"""State Agent: understands the player's current state.

Deterministic (rule-based) brain: canonicalises the player's location through an
alias table, summarises quest progress from the knowledge base, and produces a
template summary, so the output is always grounded in the actual state and the
demo needs no credentials.
"""

from __future__ import annotations

import logging

from app.data.mock_knowledge import KnowledgeBase, build_default_knowledge
from app.state import PlanningState

logger = logging.getLogger(__name__)

_KB = build_default_knowledge()

_ALIASES = {
    "stockpot": "Stockpot Inn",
    "inn": "Stockpot Inn",
    "mailbox": "Market District",
    "market": "Market District",
    "shop": "Curiosity Shop",
    "curiosity": "Curiosity Shop",
    "clocktown": "South Clock Town",
    "north town": "North Clock Town",
}


def run(state: PlanningState) -> dict:
    """Canonicalise the player's state and produce a summary.

    args:
        state (PlanningState): the workflow state with the raw game state.

    returns:
        dict: updated ``game_state`` with canonical location,
        ``state_summary`` string and ``state_engine``.
    """
    gs = state.game_state.model_copy(
        update={"location": _canonical_location(state.game_state.location)}
    )
    summary = (
        f"{gs.location} at {gs.time}. "
        f"Items: {', '.join(gs.inventory) or 'none'}. "
        f"Masks: {', '.join(gs.masks) or 'none'}."
    )
    progress = _progress_summary(gs.quest_progress, _KB)
    if progress:
        summary += f"\n{progress}"
    prefs = state.preferences.summary() if hasattr(state, "preferences") else "none"
    if prefs and prefs != "none":
        summary += f"\nPreferences: {prefs}"
    logger.info(
        "State Agent [rule-based]: location %r -> %r — summary=%r",
        state.game_state.location,
        gs.location,
        summary,
    )
    return {"game_state": gs, "state_summary": summary, "state_engine": "rule-based"}


def _progress_summary(quest_progress: dict[str, str], kb: KnowledgeBase) -> str:
    """Describe the quests the player has completed.

    Only whole-quest completion is known, so the summary never guesses an
    "active" quest from the player's location: a position only says where the
    player is, not what they are doing.

    args:
        quest_progress (dict[str, str]): quest id to status map; "done" marks
        a whole quest completed.
        kb (KnowledgeBase): the game knowledge, for quest names.

    returns:
        str: the completed-quest line, or "" when nothing is completed.
    """
    done = {qid for qid, status in quest_progress.items() if status == "done"}
    completed = [q.name for q in kb.quests if q.id in done]
    if not completed:
        return ""
    return f"Completed quests: {', '.join(completed)}."


def _canonical_location(location: str) -> str:
    """Map a free-text location to its canonical name via the alias table.

    args:
        location (str): the raw location string from the player state.

    returns:
        str: the canonical location name, or the trimmed input when no alias
        matches.
    """
    return _ALIASES.get(location.strip().lower(), location.strip())
