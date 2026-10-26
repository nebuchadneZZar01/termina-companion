"""Tests for the wiki Markdown cleanup used by evidence and prompts."""

from __future__ import annotations

from app.rag.text import clean_wiki_markdown


def test_clean_wiki_markdown_keeps_link_labels_only() -> None:
    text = (
        "The Letter to Kafei can be given to "
        '[???](/wiki/%3F%3F%3F_(Majora%27s_Mask) "??? (Majora\'s Mask)") '
        "and rewards the "
        "[Couple's Mask](/wiki/Couple%27s_Mask \"Couple's Mask\")."
    )

    cleaned = clean_wiki_markdown(text)

    assert cleaned == ("The Letter to Kafei can be given to ??? and rewards the Couple's Mask.")
    assert "](/wiki" not in cleaned
    assert '\\"' not in cleaned


def test_clean_wiki_markdown_strips_inline_formatting() -> None:
    text = "**Bold** and *italic* and `inline code` plus ![alt](/images/mask.png)"

    assert clean_wiki_markdown(text) == "Bold and italic and inline code plus alt"


def test_clean_wiki_markdown_preserves_escaped_literals() -> None:
    text = r"Anju\_s Anguish \*literal\*"

    assert clean_wiki_markdown(text) == "Anju_s Anguish *literal*"


def test_clean_wiki_markdown_is_idempotent_and_keeps_line_boundaries() -> None:
    text = "line one [A](/a)\nline two **B**"

    cleaned = clean_wiki_markdown(text)

    assert cleaned == "line one A\nline two B"
    assert clean_wiki_markdown(cleaned) == cleaned


def test_clean_wiki_markdown_leaves_plain_text_untouched() -> None:
    text = "Anju waits at the Stockpot Inn until 21:05."

    assert clean_wiki_markdown(text) == text
