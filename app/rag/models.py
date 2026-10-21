"""Pydantic contracts for wiki-backed RAG documents, chunks, evidence and sources."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RetrievalStatus = Literal["cache_hit", "wiki_ingested", "wiki_miss", "unavailable", "disabled"]


class SourceMetadata(BaseModel):
    """Provenance attached to a source document or retrieved chunk."""

    id: str
    title: str
    quest_id: str = ""
    area: str = ""
    source_type: str = "wiki"
    source_url: str = ""
    source_urls: list[str] = Field(default_factory=list)
    canonical_url: str = ""
    source_page_id: int | None = None
    source_revision_id: int | None = None
    source_revision_timestamp: str = ""
    retrieved_at: str = ""
    language: str = ""
    license_note: str = ""
    license_url: str = ""
    categories: list[str] = Field(default_factory=list)


class IndexedSource(SourceMetadata):
    """Provenance manifest entry for a page successfully added to the index.

    The manifest is intentionally separate from :class:`RetrievedChunk`: it
    describes every page indexed during a miss, including pages whose chunks do
    not pass the final evidence threshold. Only retrieved chunks are intended
    for planner context.
    """

    @classmethod
    def from_metadata(cls, metadata: SourceMetadata) -> "IndexedSource":
        """Build a manifest entry without dropping source metadata."""
        return cls.model_validate(metadata.model_dump())


class Document(BaseModel):
    """A complete source document fetched from the configured wiki."""

    id: str
    title: str
    content: str
    metadata: SourceMetadata


class Chunk(BaseModel):
    """A bounded text span that can be retrieved independently."""

    id: str
    document_id: str
    title: str
    text: str
    ordinal: int = 0
    section: str = ""
    metadata: SourceMetadata


class RetrievedChunk(BaseModel):
    """A scored chunk returned by a retriever."""

    chunk: Chunk
    score: float
    matched_terms: list[str] = Field(default_factory=list)


# Evidence is the public name used by the workflow and UI. Keep the concrete
# model name available for callers that need to inspect the nested chunk.
Evidence = RetrievedChunk


class RetrievalResult(BaseModel):
    """Result of one adaptive cache-aside retrieval request.

    ``status`` reports the outcome (cache hit, ingested, miss, unavailable,
    disabled), while ``wiki_unreachable`` independently records whether the
    wiki leg failed because the wiki could not be reached. A wiki that is
    reachable but returns an API error or no usable page is a miss, not an
    unreachable source.
    """

    query: str
    evidence: list[RetrievedChunk] = Field(default_factory=list)
    engine: str = "unknown"
    status: RetrievalStatus = "wiki_miss"
    warning: str = ""
    wiki_unreachable: bool = False
    ingested_pages: list[str] = Field(default_factory=list)
    indexed_sources: list[IndexedSource] = Field(default_factory=list)

    @property
    def chunks(self) -> list[Chunk]:
        """Return only the chunks, preserving retrieval order."""
        return [item.chunk for item in self.evidence]
