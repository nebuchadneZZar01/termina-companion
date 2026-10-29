"""Workflow state shared across LangGraph nodes."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.data.mock_knowledge import Objective
from app.domain import GameState, Goal, Plan, ValidationResult
from app.memory.models import Episode, PlayerPreferences
from app.rag.models import Evidence, IndexedSource


class AttemptRecord(BaseModel):
    """One planning attempt, recorded as the run makes it.

    The Critic writes one record per attempt, so the trajectory of a run
    (how many attempts, what each one looked like, why it was rejected) is
    available to the evaluator instead of being flattened into the last
    validation.
    """

    attempt: int = 1
    step_count: int = 0
    objective_refs: list[str] = Field(default_factory=list)
    valid: bool = False
    issue_kinds: list[str] = Field(default_factory=list)


class PlanningState(BaseModel):
    """Mutable state of the planning workflow, threaded through the graph."""

    game_state: GameState
    goal: Goal
    llm_config: dict = Field(default_factory=dict)
    state_summary: str = ""
    relevant_objectives: list[Objective] = Field(default_factory=list)
    # MCP tools invoked by the Knowledge Agent, as "tool" or "tool:<arg>".
    tool_calls: list[str] = Field(default_factory=list)
    retrieved_context: str = ""
    # One rendered planner context block per objective, so the planner can drop
    # the objectives the clock has already closed without editing text.
    planner_context_blocks: dict[str, str] = Field(default_factory=dict)
    # The supplemental RAG evidence tail, appended after the live blocks.
    planner_context_suffix: str = ""
    retrieved_evidence: list[Evidence] = Field(default_factory=list)
    retrieval_engine: str = ""
    retrieval_status: str = ""
    retrieval_warning: str = ""
    retrieval_wiki_unreachable: bool = False
    retrieval_ingested_pages: list[str] = Field(default_factory=list)
    retrieval_indexed_sources: list[IndexedSource] = Field(default_factory=list)
    plan: Plan | None = None
    # The LLM's proposal before grounding/dedup/reconcile (last attempt).
    plan_proposal: Plan | None = None
    # One record per planning attempt, oldest first (trajectory evaluation).
    attempt_log: list[AttemptRecord] = Field(default_factory=list)
    validation: ValidationResult | None = None
    replan_attempts: int = 0
    preferences: PlayerPreferences = Field(default_factory=PlayerPreferences)
    relevant_episodes: list[Episode] = Field(default_factory=list)
    memory_engine: str = ""
    state_engine: str = ""
    knowledge_engine: str = ""
    plan_engine: str = ""
    plan_model: str = ""
    critic_engine: str = ""
