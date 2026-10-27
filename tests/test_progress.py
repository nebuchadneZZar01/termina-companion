"""Objective-level progress: the declared set is the only truth."""

from app.agents.progress import done_objective_ids, objective_labels, progress_summary
from app.data.mock_knowledge import build_default_knowledge


def _kb():
    return build_default_knowledge()


def test_done_ids_are_exactly_the_declared_objectives():
    """Only the declared objectives count: no chain position is inferred."""
    kb = _kb()
    done = done_objective_ids(kb.quests, ["ak_meet_in_kitchen"], {})
    assert done == {"ak_meet_in_kitchen"}


def test_done_quest_expands_to_all_its_objectives():
    """A quest marked done counts as every one of its objectives."""
    kb = _kb()
    done = done_objective_ids(kb.quests, [], {"anju_kafei": "done"})
    assert {"ak_get_kafei_mask", "ak_reunite"} <= done
    assert len(done) == 9


def test_unknown_objective_ids_are_kept_without_side_effects():
    """An id that matches nothing is harmless, so saves stay loadable."""
    kb = _kb()
    done = done_objective_ids(kb.quests, ["gone_objective"], {})
    assert done == {"gone_objective"}


def test_progress_summary_reports_partial_progress():
    """The summary names the furthest objective done in an unfinished quest."""
    kb = _kb()
    out = progress_summary(kb.quests, ["ak_get_kafei_mask"], {})
    assert "Anju and Kafei in progress: Get Kafei's Mask from Madame Aroma done." in out


def test_progress_summary_reports_nothing_without_progress():
    """No progress means no line at all, not an empty sentence."""
    kb = _kb()
    assert progress_summary(kb.quests, [], {}) == ""


def test_objective_labels_prefix_the_quest():
    """Picker labels carry the quest name so a flat widget stays readable."""
    labels = objective_labels(_kb())
    assert labels["ak_reunite"].startswith("Anju and Kafei: ")
