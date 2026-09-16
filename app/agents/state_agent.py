"""State Agent: understands the player's current state.

Deterministic (rule-based) brain: canonicalises the player's location through an
alias table and produces a template summary, so the output is always grounded in
the actual state and the demo needs no credentials.
"""

from __future__ import annotations

import logging

from app.state import PlanningState

logger = logging.getLogger(__name__)

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
    gs = state.game_state.model_copy(
        update={"location": _canonical_location(state.game_state.location)}
    )
    summary = (
        f"{gs.location} at {gs.time}. "
        f"Items: {', '.join(gs.inventory) or 'none'}. "
        f"Masks: {', '.join(gs.masks) or 'none'}."
    )
    logger.info(
        "State Agent [rule-based]: location %r -> %r — summary=%r",
        state.game_state.location,
        gs.location,
        summary,
    )
    return {"game_state": gs, "state_summary": summary, "state_engine": "rule-based"}


def _canonical_location(location: str) -> str:
    return _ALIASES.get(location.strip().lower(), location.strip())
