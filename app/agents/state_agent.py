"""State Agent: understands the player's current state.

Mock behaviour: canonicalises the player's location and summarises what the
system understood. Later this node will parse free-text input and resolve
ambiguities with an LLM.
"""

from __future__ import annotations

from app.state import PlanningState

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


def _canonical_location(location: str) -> str:
    return _ALIASES.get(location.strip().lower(), location.strip())


def run(state: PlanningState) -> dict:
    gs = state.game_state.model_copy(
        update={"location": _canonical_location(state.game_state.location)}
    )
    summary = (
        f"{gs.location} at {gs.time}. "
        f"Items: {', '.join(gs.inventory) or 'none'}. "
        f"Masks: {', '.join(gs.masks) or 'none'}."
    )
    return {"game_state": gs, "state_summary": summary}
