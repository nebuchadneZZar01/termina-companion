"""Adaptive, supplemental wiki retrieval for TaIA.

The RAG package is separate from authoritative MCP game data. It searches a
persistent local Qdrant collection first and fetches Zelda Wiki pages only on a
cache miss; fetched text is always indexed and retrieved through vectors again
before it can reach the Knowledge Agent.
"""

from app.rag.chunking import chunk_document, chunk_documents
from app.rag.embeddings import (
    DEFAULT_FASTEMBED_MODEL,
    EmbeddingError,
    EmbeddingProvider,
    FastEmbedProvider,
    HashEmbeddingProvider,
    get_embedding_provider,
)
from app.rag.evaluation import (
    RAGEvaluationReport,
    RetrievalRunner,
    RetrievalScenario,
    RetrievalScenarioResult,
    evaluate_retrieval,
)
from app.rag.models import (
    Chunk,
    Document,
    Evidence,
    IndexedSource,
    RetrievalResult,
    RetrievedChunk,
    SourceMetadata,
)
from app.rag.retriever import (
    AdaptiveRetriever,
    RAGError,
    RAGSettings,
    build_default_retriever,
    retrieve,
)
from app.rag.store import InMemoryVectorStore, QdrantVectorStore, VectorStoreError
from app.rag.wiki import MediaWikiClient, WikiError, WikiPageReference

__all__ = [
    "AdaptiveRetriever",
    "Chunk",
    "DEFAULT_FASTEMBED_MODEL",
    "Document",
    "EmbeddingError",
    "EmbeddingProvider",
    "Evidence",
    "FastEmbedProvider",
    "HashEmbeddingProvider",
    "InMemoryVectorStore",
    "IndexedSource",
    "MediaWikiClient",
    "QdrantVectorStore",
    "RAGEvaluationReport",
    "RAGError",
    "RAGSettings",
    "RetrievalResult",
    "RetrievalRunner",
    "RetrievalScenario",
    "RetrievalScenarioResult",
    "RetrievedChunk",
    "SourceMetadata",
    "VectorStoreError",
    "WikiError",
    "WikiPageReference",
    "build_default_retriever",
    "chunk_document",
    "chunk_documents",
    "evaluate_retrieval",
    "get_embedding_provider",
    "retrieve",
]
