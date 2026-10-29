"""Documentation guards: the README must match what the code actually ships.

The evaluation tables are the ones a reader trusts when comparing sweeps, and
they drifted once already (a stale scenario count and an id that did not
exist). These tests turn that class of drift into a failure instead of a
wrong claim.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.evaluation import evaluator
from app.evaluation.scenarios import EVALUATION_SCENARIOS

_README = Path(__file__).resolve().parents[1] / "README.md"
_SCENARIOS_HEADER = "It ships twelve scenarios"
_CHECKS_HEADER = "it runs ten checks:"


def _section(text: str, start: str, end: str) -> str:
    """Return the text between two anchors, failing loudly when one is gone.

    args:
        text (str): the document.
        start (str): the anchor the section begins after.
        end (str): the anchor the section ends before.

    returns:
        str: the enclosed text.
    """
    assert start in text, f"README lost its {start!r} anchor"
    tail = text.split(start, 1)[1]
    assert end in tail, f"README section starting at {start!r} lost its end anchor"
    return tail.split(end, 1)[0]


def _documented_scenario_ids() -> set[str]:
    """Scenario ids listed in the README table."""
    table = _section(_README.read_text(encoding="utf-8"), _SCENARIOS_HEADER, "The evaluator")
    return set(re.findall(r"^\| `([a-z0-9-]+)` \|", table, re.MULTILINE))


def _documented_check_kinds() -> set[str]:
    """Check kinds listed in the README evaluator table."""
    table = _section(_README.read_text(encoding="utf-8"), _CHECKS_HEADER, "The last three evaluate")
    return set(re.findall(r"^\| `([a-z_]+)` \|", table, re.MULTILINE))


def _evaluator_check_kinds() -> set[str]:
    """Check kinds the evaluator's own docstring documents."""
    return set(re.findall(r"\* ``([a-z_]+)``", evaluator.__doc__ or ""))


def test_readme_documents_every_scenario_and_no_other():
    """The shipped scenarios and the README table are the same set."""
    assert _documented_scenario_ids() == {scenario.id for scenario in EVALUATION_SCENARIOS}


def test_readme_documents_the_same_checks_as_the_evaluator():
    """The check table and the evaluator docstring cannot drift apart."""
    assert _documented_check_kinds() == _evaluator_check_kinds()
