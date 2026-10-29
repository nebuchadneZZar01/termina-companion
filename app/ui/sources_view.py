"""Game and wiki sources rendering."""

from __future__ import annotations

import html

import streamlit as st

from app.i18n import t, tr
from app.rag.text import clean_wiki_markdown
from app.ui.formatting import (
    _entities_html,
    _entity_index,
    _entity_span,
    _fmt_timestamp,
    _highlight_entities,
    _html_clock,
    _window_range,
)
from app.ui.theme import _html_block


def _render_sources(objectives, kb) -> None:
    """Render the game-sources tab for the retrieved objectives.

    args:
        objectives (list[Objective]): the objectives to source.
        kb (KnowledgeBase): the knowledge base to resolve NPCs/events.

    returns:
        None: draws into the app.
    """
    if not objectives:
        st.write(t("no_sources"))
        return
    entities = _entity_index(kb)
    cards = []
    for obj in objectives:
        lines = [
            f"{html.escape(t('source_when'))} {_html_clock(obj.window.start)} "
            f"\u2192 {_html_clock(obj.window.end)}",
            f"{html.escape(t('source_where'))} {_entity_span(tr(obj.location), 'place')}",
        ]
        if obj.npc_id:
            npc = kb.npc(obj.npc_id)
            if npc:
                slots = " \u00b7 ".join(_window_range(w) for w in npc.schedule)
                lines.append(
                    f"{html.escape(t('source_npc'))} {html.escape(tr(npc.name))} "
                    f"\u00b7 {html.escape(t('source_active'))} {slots}"
                )
        if obj.event_ref:
            event = kb.event(obj.event_ref)
            if event:
                lines.append(
                    f"{html.escape(t('source_event'))} {html.escape(tr(event.name))} "
                    f"\u00b7 {_window_range(event.window)}"
                )
        if obj.requires_items:
            items = _entities_html(obj.requires_items, "item")
            lines.append(f"{html.escape(t('source_needs'))} {items}")
        if obj.requires_masks:
            masks = _entities_html(obj.requires_masks, "mask")
            lines.append(f"{html.escape(t('source_masks'))} {masks}")
        prereq_titles = [o.title for o in kb.all_objectives if o.id in obj.prerequisites]
        if prereq_titles:
            prereqs = ", ".join(_highlight_entities(title, entities) for title in prereq_titles)
            lines.append(f"{html.escape(t('source_after'))} {prereqs}")
        body = "".join(f'<div class="tc-detail-line">{line}</div>' for line in lines)
        cards.append(
            '<div class="tc-detail-card">'
            f'<div class="tc-detail-title">\U0001f50d '
            f"{_highlight_entities(obj.title, entities)}</div>"
            f"{body}</div>"
        )
    _html_block(f'<div class="tc-detail-list">{"".join(cards)}</div>')


def _render_rag_source(source) -> None:
    """Render one indexed wiki page and its complete provenance manifest.

    The page opens as a collapsed expander headed by its title, so a long
    indexed list stays scannable while the full provenance stays one click away.
    """
    with st.expander(tr(source.title)):
        page_id = source.source_page_id if source.source_page_id is not None else source.id
        if page_id:
            st.caption(f"{t('rag_page_id')}: {page_id}")
        if source.source_revision_id is not None:
            st.caption(
                f"{t('rag_revision')}: {source.source_revision_id} "
                f"({_fmt_timestamp(source.source_revision_timestamp)})"
            )
        if source.source_url:
            st.markdown(f"{t('rag_revision_url')}: [{source.source_url}]({source.source_url})")
        if source.canonical_url:
            st.markdown(
                f"{t('rag_canonical_url')}: [{source.canonical_url}]({source.canonical_url})"
            )
        license_text = source.license_note or "-"
        if source.license_url:
            license_text = f"{license_text} · [{t('rag_license_link')}]({source.license_url})"
        st.caption(f"{t('rag_license')}: {license_text}")
        if source.retrieved_at:
            st.caption(f"{t('rag_retrieved_at')}: {_fmt_timestamp(source.retrieved_at)}")


def _render_rag_evidence(
    evidence,
    engine: str = "",
    status: str = "",
    warning: str = "",
    wiki_unreachable: bool = False,
    indexed_sources=None,
) -> None:
    """Render indexed source pages separately from supplemental evidence.

    The indexed-source manifest is a UI/state concern. Only ``evidence`` is
    intended for planner context, so source pages remain visible even when a
    second vector query returns no passage.
    """
    _html_block(f'<div class="tc-subhead">{html.escape(t("rag_sources"))}</div>')
    st.caption(t("rag_sources_caption"))
    if engine:
        st.caption(f"{t('rag_engine')}: `{engine}`")
    if status:
        st.caption(f"{t('rag_status')}: `{status}`")
    if wiki_unreachable:
        st.warning(t("rag_wiki_unreachable"))
    if warning:
        st.warning(f"{t('rag_warning')}: {warning}")

    sources = list(indexed_sources or [])
    if not sources:
        seen: set[str] = set()
        for item in evidence:
            source = item.chunk.metadata
            key = source.id or f"{source.source_page_id}:{source.source_revision_id}"
            if key not in seen:
                seen.add(key)
                sources.append(source)
    _html_block(f'<div class="tc-detail-title">{html.escape(t("rag_indexed_sources"))}</div>')
    if sources:
        st.caption(t("rag_indexed_sources_caption", n=len(sources)))
        for source in sources:
            _render_rag_source(source)
    else:
        st.caption(t("rag_no_indexed_sources"))

    _html_block(f'<div class="tc-subhead">{html.escape(t("rag_evidence"))}</div>')
    if not evidence:
        st.caption(t("rag_no_evidence"))
        return
    cards = []
    for item in evidence:
        metadata = item.chunk.metadata
        source = metadata.display_url
        excerpt = " ".join(clean_wiki_markdown(item.chunk.text).split())
        if len(excerpt) > 600:
            excerpt = excerpt[:597].rstrip() + "..."
        revision = ""
        if metadata.source_revision_id is not None:
            revision = (
                f'<div class="tc-detail-muted">'
                f"{html.escape(t('rag_revision'))}: {metadata.source_revision_id} "
                f"({html.escape(_fmt_timestamp(metadata.source_revision_timestamp))})"
                "</div>"
            )
        cards.append(
            '<div class="tc-detail-card">'
            f'<div class="tc-detail-title">{html.escape(tr(metadata.title))} '
            f'<span class="tc-detail-muted">\u00b7 {html.escape(t("rag_score"))}: '
            f"{item.score:.3f}</span></div>"
            f'<div class="tc-detail-line">{html.escape(excerpt)}</div>'
            f'<div class="tc-detail-muted">{html.escape(t("rag_source"))}: '
            f'<a class="tc-detail-link" href="{html.escape(source, quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">{html.escape(source)}</a></div>'
            f"{revision}</div>"
        )
    _html_block(f'<div class="tc-detail-list">{"".join(cards)}</div>')
