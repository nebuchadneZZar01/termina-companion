"""Slides guards: the deck declares roles, one stylesheet owns the look.

The deck's Mermaid fences must stay free of style so every diagram shares the
same rendering, and a role the deck names must actually be styled. The build
already refuses a leaky fence, but the deck is only built by hand, so nothing
would notice a regression before a manual build.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_STAGER = _ROOT / "scripts" / "slides" / "stage.py"
_DECK = _ROOT / "docs" / "slides.md"
_CSS = _ROOT / "docs" / "mermaid.css"

_FENCE = re.compile(r"^```mermaid\n(.*?)^```$", re.MULTILINE | re.DOTALL)
_ROLE = re.compile(r"^class\s+[\w,\s]+?\s+([A-Za-z]\w*)\s*;\s*$", re.MULTILINE)
_EDGE = re.compile(r"\be_([A-Za-z][\w-]*?)@", re.MULTILINE)


def _stager():
    """Load the build script, which is not an importable package."""
    spec = importlib.util.spec_from_file_location("stage", _STAGER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fences() -> list[str]:
    return _FENCE.findall(_DECK.read_text(encoding="utf-8"))


def test_diagrams_do_not_carry_style() -> None:
    """A fence that styles itself would break the shared look."""
    check = _stager().check_diagram
    for index, fence in enumerate(_fences(), start=1):
        check(fence, index)


def test_diagram_roles_are_styled() -> None:
    """Every role the deck names has a rule in the shared stylesheet."""
    css = _CSS.read_text(encoding="utf-8")
    for fence in _fences():
        for role in _ROLE.findall(fence):
            assert f".{role} rect" in css, f"role {role!r} is not styled in docs/mermaid.css"


def test_diagram_edges_are_styled() -> None:
    """Every edge role the deck tags has a rule in the shared stylesheet."""
    css = _CSS.read_text(encoding="utf-8")
    for fence in _fences():
        for tag in _EDGE.findall(fence):
            role = tag.rstrip("0123456789") or tag
            assert f'data-edge-role="{role}"' in css, (
                f"edge role {role!r} is not styled in docs/mermaid.css"
            )


_CODE = """```python title="graph.py"
# Builds the graph of the four agents
graph = StateGraph(PlanningState)
graph.add_node("state", state_agent.run)


def start(value: int = 1):
    return value
```"""


def _code_panel(markdown: str = _CODE) -> str:
    stager = _stager()
    match = stager.CODE_FENCE.search(markdown)
    assert match is not None, "the sample is not a titled fence"
    return stager.code_panel(match)


def test_code_panel_colours_the_mockup_tokens() -> None:
    """The panel carries the same token kinds the mockup colours."""
    panel = _code_panel()
    assert '<span class="tok-comment"># Builds the graph of the four agents</span>' in panel
    assert '<span class="tok-op">=</span>' in panel
    assert '<span class="tok-class">StateGraph</span>' in panel
    assert '<span class="tok-call">add_node</span>' in panel
    assert '<span class="tok-string">&quot;state&quot;</span>' in panel
    assert '<span class="tok-keyword">def</span>' in panel
    assert '<span class="tok-number">1</span>' in panel
    # The mockup leaves a class passed as an argument, and an uncalled
    # attribute, in the default text colour.
    assert '<span class="tok-class">PlanningState</span>' not in panel
    assert "state_agent.run" in panel


def test_code_panel_escapes_source() -> None:
    """A snippet is text, never markup."""
    panel = _code_panel(
        '```python title="x.py"\nprint("<b>")\n```',
    )
    assert "&lt;b&gt;" in panel
    assert "<b>" not in panel


def test_code_panel_leaves_other_languages_plain() -> None:
    """Only Python snippets get token spans."""
    panel = _code_panel('```bash title="run.sh"\nuv run pytest\n```')
    assert "tok-" not in panel
    assert "uv run pytest" in panel


def test_code_panel_survives_invalid_python() -> None:
    """A snippet that does not parse still renders, just unstyled."""
    panel = _code_panel('```python title="x.py"\ndef broken(\n```')
    assert "tok-" not in panel
    assert "def broken(" in panel


def test_code_token_classes_are_styled() -> None:
    """Every token class the build emits has a colour in the theme."""
    css = (_ROOT / "docs" / "marp-theme.css").read_text(encoding="utf-8")
    panel = _code_panel()
    classes = set(re.findall(r'class="(tok-[a-z]+)"', panel))
    assert classes, "the sample produced no token spans"
    for name in sorted(classes):
        assert f".code .{name}" in css, f"token class {name!r} is not styled"


_DECK_SAMPLE = """---
marp: true
paginate: true
---

<!-- _class: cover -->
<!-- _paginate: false -->

Cover

---

<!-- _class: light t1 -->

## Content

---

<!-- _class: closing -->
<!-- _paginate: false -->

Closing
"""


def test_page_numbers_skip_the_unpaginated_slides() -> None:
    """Cover and closing stay out of the deck's own count."""
    stager = _stager()
    assert stager.numbered_slides(_DECK_SAMPLE) == [1]


def test_page_numbers_are_real_spans_not_marp_pagination() -> None:
    """Marp strips `content` from a theme's `section::after`, so the count is a span."""
    staged = _stager().inject_page_numbers(_DECK_SAMPLE)
    assert staged.count('class="page-no"') == 1
    assert '<span class="page-no">1 / 1</span>' in staged
    assert staged.index('class="page-no"') > staged.index("## Content")


def test_page_number_never_swallows_the_next_slide() -> None:
    """The span needs its own blank line, or Marp stops seeing the `---` break."""
    staged = _stager().inject_page_numbers(_DECK_SAMPLE)
    assert "</span>\n\n---\n" in staged


def test_page_numbers_match_the_shipped_deck() -> None:
    """Every numbered slide of the real deck gets exactly one span."""
    stager = _stager()
    deck = _DECK.read_text(encoding="utf-8")
    staged = stager.inject_page_numbers(deck)
    total = len(stager.numbered_slides(deck))
    spans = re.findall(r'<span class="page-no">(\d+) / (\d+)</span>', staged)
    assert len(spans) == total
    assert [int(page) for page, _ in spans] == list(range(1, total + 1))
    assert {denominator for _, denominator in spans} == {str(total)}
