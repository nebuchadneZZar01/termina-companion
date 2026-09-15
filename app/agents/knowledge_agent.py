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
    context = "\n".join(f"- {o.title} ({o.location}, {o.window})" for o in objectives)
    return {
        "relevant_objectives": objectives,
        "retrieved_context": context or "No relevant objectives found.",
    }
