"""Knowledge Agent: gathers structured MCP data and supplemental wiki RAG evidence.

MCP tools remain authoritative for objectives, schedules, events, prerequisites,
items and masks. The RAG seam is invoked immediately before planning, searches a
persistent Qdrant cache first, and only then may fetch and ingest Zelda Wiki
pages. Wiki text is never returned directly: it must pass through vector
retrieval again before being appended to planner context. The provenance-only
indexed-source manifest is kept in workflow state for UI inspection.
"""

from __future__ import annotations

import logging
import re

from app.data.mock_knowledge import Objective
from app.mcp.tools import get_event, get_npc_schedule, search_quests
from app.rag.retriever import RetrievalResult, retrieve
from app.state import PlanningState

logger = logging.getLogger(__name__)

_SEARCH_TOKEN_RE = re.compile(r"[A-ZÀ-ÖØ-Ý][\wÀ-ÖØ-öø-ÿ'’-]+")


def run(state: PlanningState) -> dict:
    """Gather objectives, schedules, events and supplemental wiki evidence."""
    quests = search_quests(state.goal.description, state.game_state.quest_progress)
    objectives = [Objective.model_validate(obj) for quest in quests for obj in quest["objectives"]]
    _log_objectives(objectives)
    npc_schedules = {obj.npc_id: get_npc_schedule(obj.npc_id) for obj in objectives if obj.npc_id}
    events = {obj.event_ref: get_event(obj.event_ref) for obj in objectives if obj.event_ref}
    structured_context = _format(objectives, npc_schedules, events)
    retrieval = _retrieve_evidence(state, objectives, npc_schedules)
    return {
        "relevant_objectives": objectives,
        "retrieved_context": _append_rag_context(structured_context, retrieval),
        "retrieved_evidence": retrieval.evidence,
        "retrieval_engine": retrieval.engine,
        "retrieval_status": retrieval.status,
        "retrieval_warning": retrieval.warning,
        "retrieval_wiki_unreachable": retrieval.wiki_unreachable,
        "retrieval_ingested_pages": retrieval.ingested_pages,
        "retrieval_indexed_sources": retrieval.indexed_sources,
        "knowledge_engine": "rule-based",
    }


def _retrieve_evidence(
    state: PlanningState,
    objectives: list[Objective],
    npc_schedules: dict[str, dict] | None = None,
) -> RetrievalResult:
    """Retrieve wiki evidence through the adaptive RAG seam.

    Any backend or network failure becomes a warning, while structured MCP
    context remains usable and the graph can continue.
    """
    query_parts = [state.goal.description]
    for objective in objectives:
        query_parts.extend([objective.title, objective.location, *objective.keywords])
    query = " ".join(dict.fromkeys(part for part in query_parts if part))
    search_terms = _search_terms(state.goal.description, objectives, npc_schedules or {})
    try:
        return retrieve(query, search_terms=search_terms)
    except Exception as exc:
        logger.warning("Knowledge Agent: supplemental retrieval failed: %s", exc)
        return RetrievalResult(
            query=query,
            evidence=[],
            engine="unavailable",
            status="unavailable",
            warning=str(exc),
        )


def _search_terms(
    goal: str,
    objectives: list[Objective],
    npc_schedules: dict[str, dict],
) -> list[str]:
    """Build focused MediaWiki search phrases from structured goal entities."""
    terms: list[str] = []
    _append_unique(terms, _capitalized_terms(goal))
    _append_unique(terms, _goal_tokens(goal))
    for objective in objectives:
        _append_unique(terms, objective.requires_items)
        _append_unique(terms, objective.requires_masks)
        _append_unique(terms, objective.provides_items)
        _append_unique(terms, objective.provides_masks)
        if objective.npc_id and objective.npc_id in npc_schedules:
            _append_unique(terms, [str(npc_schedules[objective.npc_id].get("name", ""))])
        _append_unique(terms, [objective.location])
    return terms[:8]


def _capitalized_terms(text: str) -> list[str]:
    return [match.group(0) for match in _SEARCH_TOKEN_RE.finditer(text)]


def _goal_tokens(text: str) -> list[str]:
    ignored = {
        "I",
        "The",
        "A",
        "An",
        "And",
        "To",
        "From",
        "At",
        "In",
        "Before",
        "After",
        "Want",
        "Need",
        "My",
    }
    return [token for token in _capitalized_terms(text) if token not in ignored]


def _append_unique(target: list[str], values: list[str]) -> None:
    seen = {item.casefold() for item in target}
    for value in values:
        normalized = " ".join(str(value).split()).strip()
        if not normalized or normalized.casefold() in seen:
            continue
        target.append(normalized)
        seen.add(normalized.casefold())


def _append_rag_context(structured_context: str, retrieval: RetrievalResult) -> str:
    """Append clearly labelled, bounded wiki evidence to planner context."""
    if not retrieval.evidence:
        if retrieval.wiki_unreachable:
            detail = f": {retrieval.warning}" if retrieval.warning else ""
            return f"{structured_context}\n\n[RAG: wiki unreachable, structured data only{detail}]"
        if retrieval.warning:
            return f"{structured_context}\n\n[RAG degraded: {retrieval.warning}]"
        return f"{structured_context}\n\n[RAG evidence: no matching passage.]"
    lines = [
        structured_context,
        "",
        "[Supplemental RAG evidence — narrative context only; its times and "
        "requirements are not planning constraints; MCP data remains authoritative]",
    ]
    lines.extend(_format_evidence(retrieval))
    return "\n".join(lines)


def _format_evidence(retrieval: RetrievalResult) -> list[str]:
    """Format retrieved chunks with compact wiki provenance information."""
    lines: list[str] = []
    for item in retrieval.evidence:
        metadata = item.chunk.metadata
        source = metadata.source_url or metadata.canonical_url or "Zelda Wiki"
        excerpt = " ".join(item.chunk.text.split())
        if len(excerpt) > 700:
            excerpt = excerpt[:697].rstrip() + "..."
        lines.append(
            f"- RAG evidence {item.chunk.id} | {metadata.title} | score={item.score:.3f}: {excerpt}"
        )
        lines.append(f"  Source: {source}")
        if metadata.source_revision_id:
            lines.append(
                f"  Revision: {metadata.source_revision_id} ({metadata.source_revision_timestamp})"
            )
    return lines


def _log_objectives(objectives) -> None:
    """Log the retrieved objectives at INFO level."""
    logger.info("Knowledge Agent [rule-based]: %d objective(s)", len(objectives))
    for obj in objectives:
        logger.info("  - %s: %s", obj.id, obj.title)


def _format(objectives, npc_schedules: dict, events: dict) -> str:
    """Format objectives and authoritative MCP context for the planner."""
    lines: list[str] = []
    for obj in objectives:
        lines.append(f"- [{obj.id}] {obj.title} ({obj.location}, {obj.window})")
        npc = npc_schedules.get(obj.npc_id)
        if npc:
            schedule = ", ".join(npc["schedule"])
            lines.append(f"  - {npc['name']}: schedule {schedule}")
        event = events.get(obj.event_ref)
        if event:
            lines.append(f"  - event: {event['name']} ({event['window']})")
        if obj.requires_masks:
            lines.append(f"  - masks needed: {', '.join(obj.requires_masks)}")
        if obj.requires_items:
            lines.append(f"  - items needed: {', '.join(obj.requires_items)}")
    return "\n".join(lines) or "No relevant objectives found."
