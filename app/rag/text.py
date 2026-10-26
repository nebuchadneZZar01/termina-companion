"""Turn wiki Markdown into readable prose for evidence and planner context."""

from __future__ import annotations

import re

# Wiki pages converted with markdownify keep inline links pointing at relative
# ``/wiki/...`` targets, including the page title as a Markdown title. Evidence
# cards and planner prompts only need the visible label, so the link target
# (and its percent-encoded path) is dropped.
_LINK_TARGET = r"(?:[^()\s]|\([^()]*\))*(?:\s+\"[^\"]*\")?\s*"
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(" + _LINK_TARGET + r"\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\(" + _LINK_TARGET + r"\)")
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
# markdownify marks strong text with ``**`` and emphasis with ``*``.
_BOLD_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.DOTALL)
_ITALIC_RE = re.compile(r"(?<!\*)\*(?=\S)(.+?)(?<=\S)\*(?!\*)", re.DOTALL)
_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!])")
# markdownify escapes literal asterisks and underscores (``\*``, ``\_``).
# Park them on private-use characters so the emphasis pass cannot consume
# them, then restore the literal marker at the end.
_ESCAPED_STAR = "\ue000"
_ESCAPED_UNDERSCORE = "\ue001"


def clean_wiki_markdown(text: str) -> str:
    """Return wiki Markdown as plain prose, keeping line boundaries.

    The transformation is idempotent: an already clean text is returned
    unchanged. It only removes inline markup, so paragraphs and newlines stay
    intact for chunking and prompt building.

    args:
        text (str): the Markdown text produced from a wiki page.

    returns:
        str: the same text with link targets, emphasis markers and inline
        code ticks removed.
    """
    if not text:
        return text
    cleaned = text.replace("\xa0", " ")
    cleaned = cleaned.replace(r"\*", _ESCAPED_STAR).replace(r"\_", _ESCAPED_UNDERSCORE)
    cleaned = _IMAGE_RE.sub(lambda match: match.group(1), cleaned)
    cleaned = _LINK_RE.sub(lambda match: match.group(1), cleaned)
    cleaned = _INLINE_CODE_RE.sub(lambda match: match.group(1), cleaned)
    cleaned = _BOLD_RE.sub(lambda match: match.group(1), cleaned)
    cleaned = _ITALIC_RE.sub(lambda match: match.group(1), cleaned)
    cleaned = cleaned.replace(_ESCAPED_STAR, "*").replace(_ESCAPED_UNDERSCORE, "_")
    return _ESCAPE_RE.sub(lambda match: match.group(1), cleaned)
