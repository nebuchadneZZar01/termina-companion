import logging

import pytest

from app import log as log_mod
from app.agents import planning_agent, state_agent
from app.agents.planning_agent import PlanningAgentError
from app.data.mock_knowledge import build_default_knowledge
from app.domain import ClockTime, GameState, Goal
from app.graph import run_pipeline
from app.log import configure_logging
from app.state import PlanningState


@pytest.fixture
def restore_root_logging():
    """Snapshot and restore the root logger so configure_logging is hermetic."""
    root = logging.getLogger()
    handlers = list(root.handlers)
    level = root.level
    noisy = {name: logging.getLogger(name).level for name in log_mod._NOISY_LOGGERS}
    yield
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level)
    for name, logger_level in noisy.items():
        logging.getLogger(name).setLevel(logger_level)


def test_configure_logging_installs_timestamped_formatter(restore_root_logging, monkeypatch):
    """The root handler uses our format, even if one was installed at import.

    Importing the app pulls in the MCP server, which calls
    ``logging.basicConfig`` with a bare ``%(message)s`` format; the old
    ``basicConfig``-based implementation was a silent no-op in that case and
    every console line lost date, level and logger name.
    """
    root = logging.getLogger()
    # Simulate the pre-existing handler that basicConfig would have left alone.
    root.addHandler(logging.StreamHandler())
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    configure_logging()

    assert len(root.handlers) == 1
    formatter = root.handlers[0].formatter
    assert formatter._fmt == log_mod._FORMAT
    assert "%(asctime)s" in formatter._fmt
    assert root.level == logging.DEBUG


def test_configure_logging_defaults_to_info(restore_root_logging, monkeypatch):
    """Without LOG_LEVEL the root logger defaults to INFO."""
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    configure_logging()
    assert logging.getLogger().level == logging.INFO


def test_configure_logging_silences_watchdogs_at_info(restore_root_logging, monkeypatch):
    """A noisy file watcher is muted at INFO but reopened at DEBUG.

    ``streamlit run`` registers its file watcher before us, so every
    filesystem event would otherwise flood an INFO console with inotify
    noise while the planning prompts scroll by. At DEBUG the caller asked
    for everything, so the watcher is deliberately left alone.
    """
    for name in log_mod._NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.DEBUG)
    monkeypatch.setenv("LOG_LEVEL", "INFO")

    configure_logging()

    for name in log_mod._NOISY_LOGGERS:
        assert logging.getLogger(name).level == logging.WARNING

    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    configure_logging()

    for name in log_mod._NOISY_LOGGERS:
        assert logging.getLogger(name).level != logging.WARNING


def _kafei_objectives():
    """Objectives matched for the Anju & Kafei goal, for prompt-only tests."""
    kb = build_default_knowledge()
    return [obj for quest in kb.quests for obj in quest.objectives if obj.id.startswith("ak_")]


def test_state_agent_logs_rule_based_path(caplog):
    """The State Agent logs that it used the rule-based path."""
    state = PlanningState(
        game_state=GameState(time=ClockTime(day=2, hour=8), location="stockpot inn"),
        goal=Goal(description="Reunite Anju and Kafei"),
    )
    with caplog.at_level(logging.INFO, logger="app.agents.state_agent"):
        state_agent.run(state)
    assert any("State Agent [rule-based]" in r.message for r in caplog.records)


class _RaisingModel:
    def with_structured_output(self, schema):
        """Return an invoke callable that always raises."""

        def _invoke(*args, **kwargs):
            raise RuntimeError("boom")

        return _invoke


def test_planning_agent_logs_llm_failure(caplog, monkeypatch):
    """The Planning Agent logs an LLM failure and does not fall back."""
    monkeypatch.setattr(planning_agent, "get_chat_model", lambda: _RaisingModel())
    state = PlanningState(
        game_state=GameState(time=ClockTime(day=2, hour=8), location="Stockpot Inn"),
        goal=Goal(description="Reunite Anju and Kafei"),
        relevant_objectives=_kafei_objectives(),
    )
    with caplog.at_level(logging.ERROR, logger="app.agents.planning_agent"):
        with pytest.raises(PlanningAgentError, match="LLM invocation failed"):
            planning_agent.run(state)
    assert any("LLM invocation failed" in r.message for r in caplog.records)


def test_planner_labels_raw_proposal_and_final_plan(caplog, fake_planner_model):
    """The planner separates the LLM's raw proposal from the reconciled plan.

    Both counts are logged, so a reader is never left wondering why a plan
    proposes N steps but prints fewer: the final plan is the one rebuilt by the
    post-processing (grounding, dedup, clamping and prerequisite chain).
    """
    state = GameState(time=ClockTime(day=2, hour=8), location="Stockpot Inn")
    goal = Goal(description="Reunite Anju and Kafei")
    with caplog.at_level(logging.INFO, logger="app.agents.planning_agent"):
        run_pipeline(state, goal)
    messages = [r.message for r in caplog.records]
    assert any("raw proposal" in message and "step(s)" in message for message in messages)
    assert any("final plan (" in message and "step(s)):" in message for message in messages)
