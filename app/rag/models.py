"""Pydantic contracts for local RAG documents, chunks and evidence."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SourceMetadata(BaseModel):
    """Provenance and search metadata attached to a source document."""

    id: str
    title: str
    quest_id: str = ""
    area: str = ""
    source_type: str = "curated_web_research"
    source_url: str = ""
    source_urls: list[str] = Field(default_factory=list)
    retrieved_at: str = ""
    language: str = ""
    license_note: str = ""


class Document(BaseModel):
    """A complete local knowledge document loaded from the corpus."""

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
    """Result of one local retrieval request."""

    query: str
    evidence: list[RetrievedChunk] = Field(default_factory=list)
    engine: str
    warning: str = ""

    @property
    def chunks(self) -> list[Chunk]:
        """Return only the chunks, preserving retrieval order.

        args:
            (none)

        returns:
            list[Chunk]: the retrieved chunks.
        """
        return [item.chunk for item in self.evidence]
