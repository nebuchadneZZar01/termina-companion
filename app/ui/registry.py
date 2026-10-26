"""Agent registry rendering."""

from __future__ import annotations

import html

from app.graph import MAX_PLANNING_ATTEMPTS
from app.i18n import t, tr
from app.ui.formatting import (
    _ENGINE_LABELS,
    _code_html,
    _engine_for,
    _entities_html,
    _entity_index,
    _entity_span,
    _fmt_window,
    _highlight_entities,
    _plain_clock,
)
from app.ui.issues import _issues_table_html, _missing_chips_html
from app.ui.progress import _progress_html, _progress_line
from app.ui.tasks import _PlanningTask

_AGENT_LABEL_KEY = {
    "state": "agent_state",
    "knowledge": "agent_knowledge",
    "plan": "agent_planning",
    "critic": "agent_critic",
}


_AGENT_SUBTITLE_KEY = {
    "state": "agent_card_state",
    "knowledge": "agent_card_knowledge",
    "plan": "agent_card_plan",
    "critic": "agent_card_critic",
}


def _rag_badges_html(result: dict) -> str:
    """Return the wiki-evidence badge row for a finished or running run."""
    status = result.get("retrieval_status") or ""
    if not status:
        return ""
    if status == "unavailable":
        tone = "red"
    elif status in {"wiki_ingested", "wiki_miss"}:
        tone = "gold"
    else:
        tone = ""
    badges = f'<span class="tc-badge {tone}">{html.escape(status)}</span>'
    sources = result.get("retrieval_indexed_sources") or []
    if sources:
        badges += f"<span>{html.escape(t('indexed_pages_n', n=len(sources)))}</span>"
    return (
        '<div class="tc-badges">'
        f'<span class="tc-badges-label">{html.escape(t("wiki_evidence"))}</span>'
        f"{badges}</div>"
    )


def _registry_rows(task: _PlanningTask) -> list[dict]:
    """Pair each streamed agent start with its progress, update and duration."""
    rows: list[dict] = []
    for index, entry in enumerate(task.log):
        kind = entry[0]
        if kind not in {"start", "update", "progress"}:
            continue
        if kind == "progress":
            payload = entry[1]
            if not isinstance(payload, dict):
                continue
            node = payload.get("node", "")
            if node not in _AGENT_LABEL_KEY:
                continue
            target = next((row for row in reversed(rows) if row["node"] == node), None)
            if target is not None:
                target["events"].append(payload)
            continue
        node = entry[1]
        if node not in _AGENT_LABEL_KEY:
            continue
        if kind == "start":
            rows.append({"node": node, "data": None, "seconds": None, "events": []})
            continue
        data = entry[2] if len(entry) > 2 else None
        if not isinstance(data, dict):
            continue
        target = next(
            (row for row in reversed(rows) if row["node"] == node and row["data"] is None),
            None,
        )
        if target is None:
            target = {"node": node, "data": None, "seconds": None, "events": []}
            rows.append(target)
        target["data"] = data
        target["seconds"] = task.timings.get(index)
    return rows


def _registry_activity_html(events: list[dict], running: bool, entities=None) -> str:
    """Return the live activity timeline for one agent row."""
    lines = [line for line in (_progress_line(event) for event in events) if line]
    if not lines:
        return ""
    index = entities or _entity_index(None)
    items = []
    for position, line in enumerate(lines):
        current = running and position == len(lines) - 1
        marker = "\u23f3" if current else "\u2713"
        tone = "current" if current else "done"
        items.append(
            f'<li class="{tone}"><span class="tc-ev">{marker}</span> '
            f"{_progress_html(line, index)}</li>"
        )
    return (
        '<div class="tc-reg-activity">'
        f'<div class="tc-panel-title">{html.escape(t("activity"))}</div>'
        f"<ul>{''.join(items)}</ul></div>"
    )


def _registry_live_summary(events: list[dict]) -> str:
    """Return the current progress line (or a starting hint) for a live row."""
    for event in reversed(events):
        line = _progress_line(event)
        if line:
            return line
    return t("agent_starting")


def _registry_engine_html(node: str, data: dict) -> str:
    """Return the engine chip for one registry row."""
    engine, model = _engine_for(node, data)
    if not engine:
        return ""
    label = html.escape(_ENGINE_LABELS.get(engine, engine))
    if model:
        label = f"{label} · {_code_html(model)}"
    return f'<span class="tc-reg-engine">{label}</span>'


def _registry_state_summary(data: dict) -> str:
    """Return the one-line State Agent result shown in the row header."""
    gs = data.get("game_state")
    if gs is None:
        return ""
    return t(
        "registry_state_summary",
        when=_plain_clock(gs.time),
        where=_entity_span(tr(gs.location), "place"),
        masks=len(gs.masks),
        items=len(gs.inventory),
    )


def _registry_plan_summary(data: dict) -> str:
    """Return the one-line Planning Agent result shown in the row header."""
    plan = data.get("plan")
    if not plan or not plan.steps:
        return t("no_plan")
    return t("registry_plan_steps", n=len(plan.steps))


def _registry_critic_summary(data: dict) -> str:
    """Return the one-line Critic result shown in the row header."""
    validation = data.get("validation")
    if validation is None:
        return ""
    if validation.valid:
        return t("plan_valid")
    return t("registry_issue_count", n=len(validation.issues))


def _registry_state_body(data: dict) -> str:
    """Return the expanded State Agent body."""
    gs = data.get("game_state")
    if gs is None:
        return ""
    items = _entities_html(gs.inventory, "item") or html.escape(t("trace_none"))
    masks = _entities_html(gs.masks, "mask") or html.escape(t("trace_none"))
    return (
        '<div class="tc-reg-kv">'
        f"<span><b>{html.escape(t('trace_items'))}</b> {items}</span>"
        f"<span><b>{html.escape(t('trace_masks'))}</b> {masks}</span>"
        "</div>"
    )


def _registry_knowledge_body(data: dict, entities=None) -> str:
    """Return the expanded Knowledge Agent body, including RAG badges."""
    objectives = data.get("relevant_objectives") or []
    index = entities if entities is not None else _entity_index(None)
    if objectives:
        items = "".join(f"<li>{_highlight_entities(obj.title, index)}</li>" for obj in objectives)
        body = f"<ul>{items}</ul>"
    else:
        body = f'<div class="tc-reg-kv">{html.escape(t("knowledge_empty_hint"))}</div>'
    return body + _rag_badges_html(data)


def _registry_plan_body(data: dict, entities=None) -> str:
    """Return the expanded Planning Agent body as a compact step list."""
    plan = data.get("plan")
    if not plan or not plan.steps:
        return f'<div class="tc-reg-kv">{html.escape(t("no_plan"))}</div>'
    index = entities if entities is not None else _entity_index(None)
    items = "".join(
        f"<li>{position}. {_highlight_entities(step.title, index)} "
        f'<span class="tc-reg-time">{html.escape(_fmt_window(step.window))}</span></li>'
        for position, step in enumerate(plan.steps, 1)
    )
    return f"<ul>{items}</ul>"


def _registry_critic_body(data: dict, entities=None) -> str:
    """Return the expanded Critic body with its issues."""
    validation = data.get("validation")
    if validation is None:
        return ""
    if validation.valid:
        return f'<div class="tc-reg-kv">{html.escape(t("plan_valid"))}</div>'
    stop = (
        f'<span class="tc-reg-stop">{html.escape(t("registry_stop_here"))}</span>'
        if len(data.get("attempt_log") or []) >= MAX_PLANNING_ATTEMPTS
        else ""
    )
    head = t("replan_line", n=len(validation.issues), max=MAX_PLANNING_ATTEMPTS)
    return (
        '<div class="tc-reg-issues-box">'
        f'<div class="tc-reg-issue-head">{html.escape(head)}{stop}</div>'
        f"{_issues_table_html(validation.issues, entities=entities)}"
        f"{_missing_chips_html(validation.issues, prefix=True)}"
        "</div>"
    )


def _registry_body(
    node: str,
    data: dict,
    *,
    events: list[dict] | None = None,
    live: bool = False,
    entities=None,
) -> str:
    """Dispatch the expanded body for one registry row."""
    if data:
        if node == "state":
            return _registry_state_body(data)
        if node == "knowledge":
            return _registry_knowledge_body(data, entities)
        if node == "plan":
            return _registry_plan_body(data, entities)
        if node == "critic":
            return _registry_critic_body(data, entities)
        return ""
    return _registry_activity_html(events or [], running=live, entities=entities)


def _registry_summary(
    node: str,
    data: dict,
    *,
    events: list[dict] | None = None,
    live: bool = False,
    entities=None,
) -> str:
    """Dispatch the HTML-safe one-line result for one registry row."""
    index = entities if entities is not None else _entity_index(None)
    if not data:
        if live:
            return _progress_html(_registry_live_summary(events or []), index)
        lines = [line for line in (_progress_line(event) for event in events or []) if line]
        return _progress_html(lines[-1], index) if lines else ""
    if node == "state":
        return _registry_state_summary(data)
    if node == "knowledge":
        return html.escape(t("knowledge_objectives", n=len(data.get("relevant_objectives") or [])))
    if node == "plan":
        return html.escape(_registry_plan_summary(data))
    if node == "critic":
        return html.escape(_registry_critic_summary(data))
    return ""


def _agent_registry_html(task: _PlanningTask, live: bool = False, kb=None) -> str:
    """Return the agent registry, shared by live and finished runs."""
    rows = _registry_rows(task)
    if not rows:
        return ""
    entities = _entity_index(kb)
    validation = task.result.get("validation")
    error_count = (
        len([issue for issue in validation.issues if issue.severity == "error"])
        if validation is not None and not validation.valid
        else 0
    )
    pill = ""
    if error_count:
        pill = (
            '<span class="tc-problems-pill">'
            f"{html.escape(t('problems_count', n=error_count))}</span>"
        )
    cards = []
    plan_attempt = 0
    last = len(rows) - 1
    for index, row in enumerate(rows):
        node = row["node"]
        data = row["data"] or {}
        running = live and row["data"] is None
        attempt = None
        if node == "plan":
            plan_attempt = int(data.get("replan_attempts") or plan_attempt + 1)
            attempt = plan_attempt
        elif node == "critic" and plan_attempt:
            attempt = plan_attempt
        bad = (
            node == "critic" and data.get("validation") is not None and not data["validation"].valid
        )
        attempt_chip = ""
        if attempt is not None:
            attempt_chip = (
                '<span class="tc-reg-attempt">'
                f"{html.escape(t('step_attempt', n=attempt, max=MAX_PLANNING_ATTEMPTS))}"
                "</span>"
            )
        seconds = row["seconds"]
        duration = f'<div class="tc-reg-time">{seconds:.1f}s</div>' if seconds is not None else ""
        classes = "tc-reg"
        if bad:
            classes += " bad"
        if running:
            classes += " running"
        summary = _registry_summary(node, data, events=row["events"], live=live, entities=entities)
        body = _registry_body(node, data, events=row["events"], live=running, entities=entities)
        cards.append(
            f'<details class="{classes}"{" open" if index == last else ""}>'
            "<summary>"
            '<span class="tc-reg-dot"></span>'
            '<div class="tc-reg-main">'
            f'<div class="tc-reg-name">{html.escape(t(_AGENT_LABEL_KEY[node]))}'
            f"{_registry_engine_html(node, data)}{attempt_chip}</div>"
            f'<div class="tc-reg-sub">{html.escape(t(_AGENT_SUBTITLE_KEY[node]))}</div>'
            "</div>"
            '<div class="tc-reg-right">'
            f'<div class="tc-reg-result">{summary}</div>'
            f"{duration}</div>"
            '<span class="tc-chev" aria-hidden="true">⌄</span>'
            "</summary>"
            f'<div class="tc-reg-body">{body}</div>'
            "</details>"
        )
    hint = t("agent_registry_live_hint") if live else t("agent_registry_hint")
    return (
        '<section class="tc-panel">'
        '<div class="tc-registry-head">'
        f'<div class="tc-panel-title">{html.escape(t("agents_title"))}</div>'
        f"{pill}</div>"
        f'<div class="tc-registry-hint">{html.escape(hint)}</div>'
        f'<div class="tc-registry">{"".join(cards)}</div>'
        "</section>"
    )
