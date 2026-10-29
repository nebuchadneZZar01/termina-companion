"""State Agent: understands the player's current state.

Deterministic brain: canonicalises the player's location through an
alias table, summarises quest progress from the knowledge base, and produces a
template summary, so the output is always grounded in the actual state and the
demo needs no credentials.
"""

from __future__ import annotations

import logging

from app.agents.progress import progress_summary
from app.data.mock_knowledge import build_default_knowledge
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
    progress = progress_summary(_KB.quests, gs.completed_objectives, gs.quest_progress)
    if progress:
        summary += f"\n{progress}"
    prefs = state.preferences.summary() if hasattr(state, "preferences") else "none"
    if prefs and prefs != "none":
        summary += f"\nPreferences: {prefs}"
    logger.info(
        "State Agent [deterministic]: location %r -> %r — summary=%r",
        state.game_state.location,
        gs.location,
        summary,
    )
    return {"game_state": gs, "state_summary": summary, "state_engine": "deterministic"}


def _canonical_location(location: str) -> str:
    """Map a free-text location to its canonical name via the alias table.

    args:
        location (str): the raw location string from the player state.

    returns:
        str: the canonical location name, or the trimmed input when no alias
        matches.
    """
    return _ALIASES.get(location.strip().lower(), location.strip())
