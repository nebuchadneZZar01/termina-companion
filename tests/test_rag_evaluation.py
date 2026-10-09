"""Tests for retrieval-only RAG evaluation metrics."""

from __future__ import annotations

from app.rag.evaluation import RetrievalScenario, evaluate_retrieval
from app.rag.models import Chunk, RetrievalResult, RetrievedChunk, SourceMetadata


class ScenarioRetriever:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int | None, list[str] | tuple[str, ...] | None]] = []

    def retrieve(self, query, top_k=None, search_terms=None):
        self.calls.append((query, top_k, search_terms))
        page_id = 4819 if "Kafei" in query else 9999
        title = "Anju's Anguish" if page_id == 4819 else "Unrelated"
        metadata = SourceMetadata(id=f"wiki:{page_id}", title=title, source_page_id=page_id)
        chunk = Chunk(
            id=f"wiki:{page_id}::chunk-000",
            document_id=metadata.id,
            title=title,
            text="text",
            metadata=metadata,
        )
        return RetrievalResult(
            query=query,
            evidence=[RetrievedChunk(chunk=chunk, score=0.9)],
            engine="test",
            status="cache_hit",
        )


def test_evaluate_retrieval_reports_page_hits_without_network() -> None:
    runner = ScenarioRetriever()
    report = evaluate_retrieval(
        runner,
        [
            RetrievalScenario(
                id="anju-kafei",
                query="Kafei and Anju",
                expected_page_ids={4819},
                expected_titles={"Anju's Anguish"},
                search_terms=["Kafei", "Anju"],
                top_k=2,
            ),
            RetrievalScenario(
                id="miss",
                query="Darmani",
                expected_page_ids={4819},
            ),
        ],
    )

    assert report.total == 2
    assert report.hits == 1
    assert report.hit_rate == 0.5
    assert report.unavailable == 0
    assert report.model_dump()["hit_rate"] == 0.5
    assert report.scenarios[0].returned_page_ids == [4819]
    assert report.scenarios[1].hit is False
    assert runner.calls[0] == ("Kafei and Anju", 2, ["Kafei", "Anju"])


def test_scenario_requires_expected_identity() -> None:
    try:
        RetrievalScenario(id="invalid", query="anything")
    except ValueError as exc:
        assert "page ID or title" in str(exc)
    else:
        raise AssertionError("expected scenario validation error")
