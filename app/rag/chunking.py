"""Deterministic, heading-aware text chunking for wiki documents."""

from __future__ import annotations

import re

from app.rag.models import Chunk, Document

_WHITESPACE_RE = re.compile(r"[ \t]+")
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")


def chunk_document(document: Document, max_chars: int = 1200, overlap: int = 120) -> list[Chunk]:
    """Split one document into overlapping chunks while retaining headings.

    Paragraph boundaries are preferred. Oversized paragraphs are split at a
    nearby whitespace boundary so words are not cut in the middle whenever
    possible. Each chunk records the Markdown heading active at that point.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap < 0 or overlap >= max_chars:
        raise ValueError("overlap must be non-negative and smaller than max_chars")
    if not document.content.strip():
        raise ValueError(f"Cannot chunk empty document: {document.id}")

    chunks: list[Chunk] = []
    for section, paragraphs in _sections(document.content):
        for paragraph in paragraphs:
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
                        section=section,
                        metadata=document.metadata.model_copy(deep=True),
                    )
                )
    if not chunks:
        raise ValueError(f"Document produced no chunks: {document.id}")
    return chunks


def chunk_documents(
    documents: list[Document], max_chars: int = 1200, overlap: int = 120
) -> list[Chunk]:
    """Chunk a collection of documents while preserving global order."""
    return [
        chunk
        for document in documents
        for chunk in chunk_document(document, max_chars=max_chars, overlap=overlap)
    ]


def _sections(content: str) -> list[tuple[str, list[str]]]:
    """Split Markdown into heading sections and their paragraph blocks."""
    sections: list[tuple[str, list[str]]] = []
    current_section = ""
    current_paragraph: list[str] = []

    def flush_paragraph() -> None:
        if not current_paragraph:
            return
        paragraph = "\n".join(current_paragraph).strip()
        if paragraph:
            if not sections or sections[-1][0] != current_section:
                sections.append((current_section, []))
            sections[-1][1].append(paragraph)
        current_paragraph.clear()

    for line in content.replace("\r", "").splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            flush_paragraph()
            current_section = _normalize(heading.group(2))
            continue
        if not line.strip():
            flush_paragraph()
        else:
            current_paragraph.append(line)
    flush_paragraph()
    return sections


def _normalize(text: str) -> str:
    """Collapse horizontal whitespace while retaining line boundaries."""
    return _WHITESPACE_RE.sub(" ", text).strip()


def _windows(text: str, max_chars: int, overlap: int) -> list[str]:
    """Create overlapping character windows from one normalized paragraph."""
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
