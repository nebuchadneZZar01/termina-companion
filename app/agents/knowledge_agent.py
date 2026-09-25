"""Knowledge Agent: gathers structured MCP data and supplemental RAG evidence.

The structured path is deterministic: MCP tools search objectives and return
NPC schedules and events. A local retriever adds curated narrative evidence;
it is optional and never changes the authoritative objective chain. Tools are
imported in-process from ``app.mcp.tools``; swapping them for the protocol
client (or another data source) is a drop-in change.
"""

from __future__ import annotations

import logging

from app.data.mock_knowledge import Objective
from app.mcp.tools import get_event, get_npc_schedule, search_quests
from app.rag.retriever import RetrievalResult, retrieve
from app.state import PlanningState

logger = logging.getLogger(__name__)


def run(state: PlanningState) -> dict:
    """Gather the objectives, NPC schedules and events relevant to the goal.

    args:
        state (PlanningState): the workflow state with the player's game
        state and goal.

    returns:
        dict: ``relevant_objectives``, the formatted ``retrieved_context``
        and ``knowledge_engine``.
    """
    quests = search_quests(state.goal.description, state.game_state.quest_progress)
    objectives = [Objective.model_validate(obj) for quest in quests for obj in quest["objectives"]]
    _log_objectives(objectives)
    npc_schedules = {obj.npc_id: get_npc_schedule(obj.npc_id) for obj in objectives if obj.npc_id}
    events = {obj.event_ref: get_event(obj.event_ref) for obj in objectives if obj.event_ref}
    structured_context = _format(objectives, npc_schedules, events)
    retrieval = _retrieve_evidence(state, objectives)
    return {
        "relevant_objectives": objectives,
        "retrieved_context": _append_rag_context(structured_context, retrieval),
        "retrieved_evidence": retrieval.evidence,
        "retrieval_engine": retrieval.engine,
        "retrieval_warning": retrieval.warning,
        "knowledge_engine": "rule-based",
    }


def _retrieve_evidence(state: PlanningState, objectives: list[Objective]) -> RetrievalResult:
    """Retrieve optional narrative evidence for the goal and matched objectives.

    Retrieval is intentionally isolated behind the public ``retrieve`` seam.
    Any corpus or indexing failure becomes a warning, while structured MCP
    context remains usable and the graph can continue.

    args:
        state: workflow state containing the player goal.
        objectives: structured objectives already selected by MCP.

    returns:
        RetrievalResult: evidence, engine label and optional warning.
    """
    query_parts = [state.goal.description]
    for objective in objectives:
        query_parts.extend([objective.title, objective.location, *objective.keywords])
    query = " ".join(dict.fromkeys(part for part in query_parts if part))
    try:
        return retrieve(query, top_k=4)
    except Exception as exc:
        logger.warning("Knowledge Agent: supplemental retrieval failed: %s", exc)
        return RetrievalResult(
            query=query,
            evidence=[],
            engine="unavailable",
            warning=str(exc),
        )


def _append_rag_context(structured_context: str, retrieval: RetrievalResult) -> str:
    """Append a clearly labeled RAG section to structured planner context.

    args:
        structured_context: authoritative MCP-derived context.
        retrieval: optional local retrieval result.

    returns:
        str: structured context followed by bounded source excerpts.
    """
    if retrieval.engine == "disabled":
        return structured_context
    if not retrieval.evidence:
        if retrieval.warning:
            return f"{structured_context}\n\n[RAG unavailable: {retrieval.warning}]"
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
    """Format retrieved chunks with compact provenance information.

    args:
        retrieval: local retrieval result.

    returns:
        list[str]: one bounded evidence block per retrieved chunk.
    """
    lines: list[str] = []
    for item in retrieval.evidence:
        metadata = item.chunk.metadata
        source = metadata.source_url or (
            metadata.source_urls[0] if metadata.source_urls else "local corpus"
        )
        excerpt = " ".join(item.chunk.text.split())
        if len(excerpt) > 700:
            excerpt = excerpt[:697].rstrip() + "..."
        lines.append(
            f"- RAG evidence {item.chunk.id} | {metadata.title} | score={item.score:.3f}: {excerpt}"
        )
        lines.append(f"  Source: {source}")
    return lines


def _log_objectives(objectives) -> None:
    """Log the retrieved objectives at INFO level.

    args:
        objectives (iterable[Objective]): objectives to log.

    returns:
        None: logging only.
    """
    logger.info("Knowledge Agent [rule-based]: %d objective(s)", len(objectives))
    for obj in objectives:
        logger.info("  - %s: %s", obj.id, obj.title)


def _format(objectives, npc_schedules: dict, events: dict) -> str:
    """Format objectives as a compact text context for the planner.

    Includes id, title, location, window, NPC schedule, event and any
    masks/items needed. NPC schedules and events come from the MCP tools, not
    from direct knowledge base access.

    args:
        objectives (iterable[Objective]): the objectives to format.
        npc_schedules (dict[str, dict]): npc_id to ``get_npc_schedule`` output.
        events (dict[str, dict]): event_id to ``get_event`` output.

    returns:
        str: one block per objective, or "No relevant objectives found."
        when empty.
    """
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
