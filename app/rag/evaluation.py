"""Retrieval-only evaluation contracts for RAG calibration.

This module measures whether a retriever returns expected Zelda Wiki pages. It
does not evaluate plans or trajectories; that work belongs to Phase 11.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, Field, computed_field, model_validator

from app.rag.models import RetrievalResult


class RetrievalScenario(BaseModel):
    """One query and expected wiki page identities for retrieval evaluation."""

    id: str
    query: str
    expected_page_ids: set[int] = Field(default_factory=set)
    expected_titles: set[str] = Field(default_factory=set)
    search_terms: list[str] = Field(default_factory=list)
    top_k: int = Field(default=4, gt=0, le=50)

    @model_validator(mode="after")
    def require_expected_page(self) -> "RetrievalScenario":
        if not self.query.strip():
            raise ValueError("evaluation query must not be empty")
        if not self.expected_page_ids and not self.expected_titles:
            raise ValueError("evaluation scenario needs a page ID or title")
        return self


class RetrievalScenarioResult(BaseModel):
    """Outcome for one retrieval scenario."""

    scenario_id: str
    status: str
    hit: bool
    evidence_count: int
    wiki_unreachable: bool = False
    returned_page_ids: list[int] = Field(default_factory=list)
    returned_titles: list[str] = Field(default_factory=list)
    warning: str = ""


class RAGEvaluationReport(BaseModel):
    """Aggregate retrieval-only metrics; no plan-quality claims are made."""

    scenarios: list[RetrievalScenarioResult] = Field(default_factory=list)

    @computed_field
    @property
    def total(self) -> int:
        return len(self.scenarios)

    @computed_field
    @property
    def hits(self) -> int:
        return sum(item.hit for item in self.scenarios)

    @computed_field
    @property
    def hit_rate(self) -> float:
        return self.hits / self.total if self.total else 0.0

    @computed_field
    @property
    def unavailable(self) -> int:
        return sum(item.status == "unavailable" for item in self.scenarios)


class RetrievalRunner(Protocol):
    """Minimal retriever interface used by the evaluation harness."""

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        search_terms: list[str] | tuple[str, ...] | None = None,
    ) -> RetrievalResult:
        """Retrieve evidence for one scenario."""


def evaluate_retrieval(
    runner: RetrievalRunner, scenarios: Sequence[RetrievalScenario]
) -> RAGEvaluationReport:
    """Run scenarios against an injected retriever and collect page-hit metrics.

    The caller supplies the retriever, so tests and calibration jobs can use
    an in-memory fixture without contacting Zelda Wiki or downloading FastEmbed.
    """
    results: list[RetrievalScenarioResult] = []
    for scenario in scenarios:
        result = runner.retrieve(
            scenario.query,
            top_k=scenario.top_k,
            search_terms=scenario.search_terms,
        )
        page_ids = {
            int(item.chunk.metadata.source_page_id)
            for item in result.evidence
            if item.chunk.metadata.source_page_id is not None
        }
        titles = {
            item.chunk.metadata.title.casefold().strip()
            for item in result.evidence
            if item.chunk.metadata.title
        }
        expected_titles = {title.casefold().strip() for title in scenario.expected_titles}
        hit = bool(
            page_ids.intersection(scenario.expected_page_ids)
            or titles.intersection(expected_titles)
        )
        results.append(
            RetrievalScenarioResult(
                scenario_id=scenario.id,
                status=result.status,
                hit=hit,
                evidence_count=len(result.evidence),
                wiki_unreachable=result.wiki_unreachable,
                returned_page_ids=sorted(page_ids),
                returned_titles=sorted(titles),
                warning=result.warning,
            )
        )
    return RAGEvaluationReport(scenarios=results)
