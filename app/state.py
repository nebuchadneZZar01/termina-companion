"""Workflow state shared across LangGraph nodes."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.data.mock_knowledge import Objective
from app.domain import GameState, Goal, Plan, ValidationResult


class PlanningState(BaseModel):
    """Mutable state of the planning workflow, threaded through the graph."""

    game_state: GameState
    goal: Goal
    state_summary: str = ""
    relevant_objectives: list[Objective] = Field(default_factory=list)
    retrieved_context: str = ""
    plan: Plan | None = None
    validation: ValidationResult | None = None
    replan_attempts: int = 0
    state_engine: str = ""
    knowledge_engine: str = ""
    plan_engine: str = ""
    critic_engine: str = ""
