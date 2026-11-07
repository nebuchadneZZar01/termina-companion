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
_STAGER = _ROOT / "scripts" / "stage_slides.py"
_DECK = _ROOT / "docs" / "slides.md"
_CSS = _ROOT / "docs" / "mermaid.css"

_FENCE = re.compile(r"^```mermaid\n(.*?)^```$", re.MULTILINE | re.DOTALL)
_ROLE = re.compile(r"^class\s+[\w,\s]+?\s+([A-Za-z]\w*)\s*;\s*$", re.MULTILINE)
_EDGE = re.compile(r"\be_([A-Za-z][\w-]*?)@", re.MULTILINE)


def _stager():
    """Load the build script, which is not an importable package."""
    spec = importlib.util.spec_from_file_location("stage_slides", _STAGER)
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
