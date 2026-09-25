"""Load curated local Markdown documents for the RAG layer."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

from app.rag.models import Document, SourceMetadata

DEFAULT_CORPUS_DIR = Path(__file__).resolve().parents[1] / "data" / "knowledge" / "clock_town"
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<meta>.*?)\n---\s*\n(?P<body>.*)\Z", re.DOTALL)


class DocumentLoadError(RuntimeError):
    """Raised when a corpus document cannot be parsed or validated."""


def load_documents(corpus_dir: str | Path | None = None) -> list[Document]:
    """Load all curated Markdown documents from a corpus directory.

    ``README.md`` is documentation for maintainers, not a retrievable source,
    and is intentionally skipped. Files are sorted by path for deterministic
    indexing.

    args:
        corpus_dir: directory containing Markdown documents. Defaults to the
            checked-in Clock Town corpus.

    returns:
        list[Document]: validated documents in stable filename order.

    raises:
        DocumentLoadError: if the directory is missing or a document is invalid.
    """
    directory = Path(corpus_dir) if corpus_dir is not None else DEFAULT_CORPUS_DIR
    if not directory.is_dir():
        raise DocumentLoadError(f"RAG corpus directory does not exist: {directory}")

    paths = sorted(path for path in directory.glob("*.md") if path.name.lower() != "readme.md")
    if not paths:
        raise DocumentLoadError(f"RAG corpus has no Markdown documents: {directory}")
    documents = [load_document(path) for path in paths]
    duplicate_ids = _duplicate_ids(documents)
    if duplicate_ids:
        raise DocumentLoadError("Duplicate RAG document id(s): " + ", ".join(sorted(duplicate_ids)))
    return documents


def _duplicate_ids(documents: list[Document]) -> set[str]:
    """Return document ids that occur more than once in a corpus.

    args:
        documents: loaded source documents.

    returns:
        set[str]: duplicate ids.
    """
    seen: set[str] = set()
    duplicates: set[str] = set()
    for document in documents:
        if document.id in seen:
            duplicates.add(document.id)
        seen.add(document.id)
    return duplicates


def load_document(path: str | Path) -> Document:
    """Load and validate one Markdown document with YAML-like frontmatter.

    The small frontmatter parser intentionally supports only the scalar and
    JSON-list values used by this repository. It avoids adding a YAML
    dependency to the prototype.

    args:
        path: Markdown file to read.

    returns:
        Document: validated source document.

    raises:
        DocumentLoadError: if the file cannot be read, lacks frontmatter, or
            contains invalid metadata.
    """
    file_path = Path(path)
    try:
        raw = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DocumentLoadError(f"Cannot read RAG document {file_path}: {exc}") from exc

    match = _FRONTMATTER_RE.match(raw)
    if not match:
        raise DocumentLoadError(f"RAG document has no frontmatter: {file_path}")

    metadata = _parse_frontmatter(match.group("meta"), file_path)
    body = match.group("body").strip()
    if not body:
        raise DocumentLoadError(f"RAG document has empty content: {file_path}")

    document_id = str(metadata.pop("id", "") or file_path.stem)
    title = str(metadata.pop("title", "") or document_id.replace("_", " ").title())
    known = {
        "quest_id",
        "area",
        "source_type",
        "source_url",
        "source_urls",
        "retrieved_at",
        "language",
        "license_note",
    }
    unknown = set(metadata) - known
    if unknown:
        raise DocumentLoadError(
            f"Unknown RAG metadata in {file_path}: {', '.join(sorted(unknown))}"
        )

    try:
        return Document(
            id=document_id,
            title=title,
            content=body,
            metadata=SourceMetadata(
                id=document_id,
                title=title,
                **metadata,
            ),
        )
    except Exception as exc:
        raise DocumentLoadError(f"Invalid RAG metadata in {file_path}: {exc}") from exc


def _parse_frontmatter(raw: str, path: Path) -> dict[str, Any]:
    """Parse the restricted frontmatter format used by the corpus.

    Args:
        raw: frontmatter text without the ``---`` fences.
        path: source path used in error messages.

    Returns:
        dict[str, Any]: parsed scalar/list values.

    Raises:
        DocumentLoadError: if a line is malformed or a value cannot be parsed.
    """
    result: dict[str, Any] = {}
    current_list: str | None = None
    for line_number, raw_line in enumerate(raw.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-") and current_list is not None:
            result.setdefault(current_list, []).append(
                _parse_value(line[1:].strip(), path, line_number)
            )
            continue
        if ":" not in line:
            raise DocumentLoadError(f"Malformed frontmatter at {path}:{line_number}")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise DocumentLoadError(f"Empty frontmatter key at {path}:{line_number}")
        if not value:
            if key == "source_urls":
                current_list = key
                result[key] = []
            else:
                current_list = None
                result[key] = ""
            continue
        current_list = None
        result[key] = _parse_value(value, path, line_number)
    return result


def _parse_value(value: str, path: Path, line_number: int) -> Any:
    """Parse one frontmatter scalar or JSON-like list value.

    Args:
        value: raw value text.
        path: source path used in error messages.
        line_number: source line number used in error messages.

    Returns:
        Any: parsed Python value.

    Raises:
        DocumentLoadError: if list-like syntax is invalid.
    """
    if value.startswith("[") or value.startswith("{"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            try:
                return ast.literal_eval(value)
            except (SyntaxError, ValueError) as exc:
                raise DocumentLoadError(
                    f"Invalid frontmatter value at {path}:{line_number}"
                ) from exc
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none", "~"}:
        return None
    return value
