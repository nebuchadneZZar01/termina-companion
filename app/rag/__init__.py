"""Local, supplemental retrieval for textual Majora's Mask knowledge.

The RAG package is intentionally separate from the structured MCP tools. It
loads a curated local corpus, creates chunks and exposes deterministic keyword
and in-memory vector retrieval. Retrieval evidence supplements planning context
but never replaces authoritative quest data.
"""

from app.rag.chunking import chunk_document, chunk_documents
from app.rag.loader import DEFAULT_CORPUS_DIR, DocumentLoadError, load_documents
from app.rag.models import (
    Chunk,
    Document,
    Evidence,
    RetrievalResult,
    RetrievedChunk,
    SourceMetadata,
)
from app.rag.retriever import (
    HybridRetriever,
    KeywordRetriever,
    RAGError,
    VectorRetriever,
    build_default_retriever,
    retrieve,
    safe_retrieve,
)

__all__ = [
    "Chunk",
    "DEFAULT_CORPUS_DIR",
    "Document",
    "DocumentLoadError",
    "Evidence",
    "HybridRetriever",
    "KeywordRetriever",
    "RAGError",
    "RetrievalResult",
    "RetrievedChunk",
    "SourceMetadata",
    "VectorRetriever",
    "build_default_retriever",
    "chunk_document",
    "chunk_documents",
    "load_documents",
    "retrieve",
    "safe_retrieve",
]
