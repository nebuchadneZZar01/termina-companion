"""Deterministic text chunking for locally loaded RAG documents."""

from __future__ import annotations

import re

from app.rag.models import Chunk, Document

_WHITESPACE_RE = re.compile(r"[ \t]+")
_PARAGRAPH_RE = re.compile(r"\n\s*\n")


def chunk_document(document: Document, max_chars: int = 1200, overlap: int = 120) -> list[Chunk]:
    """Split one document into overlapping, source-preserving chunks.

    Paragraph boundaries are preferred. Oversized paragraphs are split at a
    nearby whitespace boundary so words are not cut in the middle whenever
    possible.

    args:
        document: source document to split.
        max_chars: maximum approximate chunk size; must be positive.
        overlap: number of characters repeated between adjacent windows;
            must be smaller than ``max_chars``.

    returns:
        list[Chunk]: deterministic chunks in document order.

    raises:
        ValueError: if size arguments are invalid or the document is empty.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap < 0 or overlap >= max_chars:
        raise ValueError("overlap must be non-negative and smaller than max_chars")
    if not document.content.strip():
        raise ValueError(f"Cannot chunk empty document: {document.id}")

    chunks: list[Chunk] = []
    for paragraph in _PARAGRAPH_RE.split(document.content):
        normalized = _normalize(paragraph)
        if not normalized:
            continue
        for text in _windows(normalized, max_chars=max_chars, overlap=overlap):
            ordinal = len(chunks)
            chunks.append(
                Chunk(
                    id=f"{document.id}::chunk-{ordinal:03d}",
                    document_id=document.id,
                    title=document.title,
                    text=text,
                    ordinal=ordinal,
                    metadata=document.metadata.model_copy(deep=True),
                )
            )
    if not chunks:
        raise ValueError(f"Document produced no chunks: {document.id}")
    return chunks


def chunk_documents(
    documents: list[Document], max_chars: int = 1200, overlap: int = 120
) -> list[Chunk]:
    """Chunk a collection of documents while preserving global order.

    args:
        documents: source documents to split.
        max_chars: maximum approximate chunk size.
        overlap: repeated characters between adjacent windows.

    returns:
        list[Chunk]: chunks in document order.
    """
    return [
        chunk
        for document in documents
        for chunk in chunk_document(document, max_chars=max_chars, overlap=overlap)
    ]


def _normalize(text: str) -> str:
    """Collapse horizontal whitespace while retaining paragraph text.

    args:
        text: paragraph text.

    returns:
        str: normalized paragraph.
    """
    return _WHITESPACE_RE.sub(" ", text.replace("\r", "")).strip()


def _windows(text: str, max_chars: int, overlap: int) -> list[str]:
    """Create overlapping character windows from one normalized paragraph.

    Args:
        text: normalized paragraph.
        max_chars: maximum window size.
        overlap: repeated suffix size.

    Returns:
        list[str]: non-empty text windows.
    """
    if len(text) <= max_chars:
        return [text]

    windows: list[str] = []
    start = 0
    while start < len(text):
        hard_end = min(start + max_chars, len(text))
        end = hard_end
        if hard_end < len(text):
            search_start = start + max_chars // 2
            boundary = max(
                text.rfind(" ", search_start, hard_end),
                text.rfind("\n", search_start, hard_end),
            )
            if boundary > search_start:
                end = boundary
        piece = text[start:end].strip()
        if piece:
            windows.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return windows
