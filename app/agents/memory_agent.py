"""Memory Agent: retrieve past episodes before planning, store the run after.

Keeps the graph nodes thin: retrieval enriches state for the planner,
storage records only the finished run (valid or gave-up), never the
intermediate replan drafts.
"""

from __future__ import annotations

import logging
import uuid

from app.memory.models import Episode
from app.memory.store import get_memory_store
from app.progress import report
from app.state import PlanningState

logger = logging.getLogger(__name__)


def retrieve_run(state: PlanningState) -> dict:
    """Load preferences and relevant past episodes into the workflow state."""
    store = get_memory_store()
    episodes = store.search_episodes(state.goal.description, state.game_state.location)
    prefs = store.get_preferences()
    report({"node": "memory", "phase": "retrieve", "n": len(episodes)})
    logger.info("Memory [in-memory]: %d episode(s) for %r", len(episodes), state.goal.description)
    return {
        "relevant_episodes": episodes,
        "preferences": prefs,
        "memory_engine": "in-memory",
    }


def store_run(state: PlanningState) -> dict:
    """Persist the finished run as one episode. No-op without a plan."""
    if state.plan is None:
        return {"memory_engine": "in-memory"}
    summary = "; ".join(
        f"{i}. {s.title} @ {s.location} [{s.window}]" for i, s in enumerate(state.plan.steps, 1)
    )[:1500]
    episode = Episode(
        id=uuid.uuid4().hex,
        goal=state.goal.description,
        location=state.game_state.location,
        time=state.game_state.time,
        quest_progress=dict(state.game_state.quest_progress),
        plan_summary=summary,
        objective_refs=[s.objective_ref for s in state.plan.steps if s.objective_ref],
        valid=bool(state.validation and state.validation.valid),
        issues_count=len(state.validation.issues) if state.validation else 0,
    )
    get_memory_store().save_episode(episode)
    report({"node": "memory", "phase": "store", "valid": episode.valid})
    logger.info("Memory [in-memory]: stored episode %s valid=%s", episode.id, episode.valid)
    return {"memory_engine": "in-memory"}
