"""Knowledge Agent: retrieves game knowledge relevant to the current goal.

Uses the mock :class:`~app.data.mock_knowledge.KnowledgeBase`.
Replacing it with a RAG retriever later only changes what ``retrieve`` does.
"""

from __future__ import annotations

from app.data.mock_knowledge import build_default_knowledge
from app.state import PlanningState

_KB = build_default_knowledge()


def run(state: PlanningState) -> dict:
    objectives = _KB.retrieve(state.game_state, state.goal)
    lines: list[str] = []
    for obj in objectives:
        lines.append(f"- {obj.title} ({obj.location}, {obj.window})")
        npc = _KB.npc(obj.npc_id)
        if npc:
            schedule = ", ".join(str(w) for w in npc.schedule)
            lines.append(f"  - {npc.name}: schedule {schedule}")
        event = _KB.event(obj.event_ref)
        if event:
            lines.append(f"  - event: {event.name} ({event.window})")
    return {
        "relevant_objectives": objectives,
        "retrieved_context": "\n".join(lines) or "No relevant objectives found.",
    }
