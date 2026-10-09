"""Workflow state shared across LangGraph nodes."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.data.mock_knowledge import Objective
from app.domain import GameState, Goal, Plan, ValidationResult
from app.rag.models import Evidence, IndexedSource


class PlanningState(BaseModel):
    """Mutable state of the planning workflow, threaded through the graph."""

    game_state: GameState
    goal: Goal
    llm_config: dict = Field(default_factory=dict)
    state_summary: str = ""
    relevant_objectives: list[Objective] = Field(default_factory=list)
    retrieved_context: str = ""
    retrieved_evidence: list[Evidence] = Field(default_factory=list)
    retrieval_engine: str = ""
    retrieval_status: str = ""
    retrieval_warning: str = ""
    retrieval_wiki_unreachable: bool = False
    retrieval_ingested_pages: list[str] = Field(default_factory=list)
    retrieval_indexed_sources: list[IndexedSource] = Field(default_factory=list)
    plan: Plan | None = None
    validation: ValidationResult | None = None
    replan_attempts: int = 0
    state_engine: str = ""
    knowledge_engine: str = ""
    plan_engine: str = ""
    plan_model: str = ""
    critic_engine: str = ""
