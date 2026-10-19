"""Focused Streamlit rendering and planning-task lifecycle tests."""

from __future__ import annotations

import queue
import threading

import pytest

from app import ui
from app.rag.models import IndexedSource, SourceMetadata


class _Container:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Placeholder:
    """Stand-in for the invisible yield placeholder of the live loop."""

    def __init__(self, stub: _StreamlitStub) -> None:
        self.stub = stub

    def empty(self) -> _Placeholder:
        self.stub.emptied += 1
        return self


class _StreamlitStub:
    def __init__(self) -> None:
        self.session_state: dict[str, str] = {}
        self.calls: list[tuple[str, str]] = []
        self.emptied = 0

    def container(self, **_kwargs):
        return _Container()

    def empty(self) -> _Placeholder:
        return _Placeholder(self)

    def markdown(self, value: str, **_kwargs) -> None:
        self.calls.append(("markdown", value))

    def caption(self, value: str, **_kwargs) -> None:
        self.calls.append(("caption", value))

    def write(self, value: str, **_kwargs) -> None:
        self.calls.append(("write", value))

    def warning(self, value: str, **_kwargs) -> None:
        self.calls.append(("warning", value))

    def expander(self, label: str, **_kwargs) -> _Container:
        self.calls.append(("expander", label))
        return _Container()


def _source() -> IndexedSource:
    return IndexedSource.from_metadata(
        SourceMetadata(
            id="wiki:4819",
            title="Anju's Anguish",
            source_page_id=4819,
            source_revision_id=1380158,
            source_revision_timestamp="2026-01-02T03:04:05Z",
            source_url="https://zeldawiki.wiki/w/index.php?oldid=1380158",
            canonical_url="https://zeldawiki.wiki/wiki/Anju's_Anguish",
            license_note="GNU Free Documentation License 1.3",
            license_url="https://zeldawiki.wiki/wiki/Zelda_Wiki:GNU_Free_Documentation_License",
            retrieved_at="2026-01-03T04:05:06Z",
        )
    )


def test_render_rag_manifest_shows_sources_when_evidence_is_empty(monkeypatch):
    stub = _StreamlitStub()
    monkeypatch.setattr(ui, "st", stub)
    monkeypatch.setattr(ui, "t", lambda key, **kwargs: key.format(**kwargs) if kwargs else key)
    monkeypatch.setattr(ui, "tr", lambda value: value)

    ui._render_rag_evidence(
        [],
        engine="qdrant-fastembed",
        status="wiki_miss",
        indexed_sources=[_source()],
    )

    rendered = "\n".join(value for _kind, value in stub.calls)
    assert "Anju's Anguish" in rendered
    assert "4819" in rendered
    assert "1380158" in rendered
    assert "oldid=1380158" in rendered
    assert "Anju's_Anguish" in rendered
    assert "GNU Free Documentation License 1.3" in rendered
    assert "3 Jan 2026, 04:05 UTC" in rendered
    assert "rag_no_evidence" in rendered
    # Indexed pages collapse into expanders titled by page.
    assert ("expander", "Anju's Anguish") in stub.calls
    assert "`qdrant-fastembed`" in rendered
    assert "`wiki_miss`" in rendered


def test_fmt_timestamp_humanises_iso_in_both_languages(monkeypatch) -> None:
    stub = _StreamlitStub()
    monkeypatch.setattr(ui, "st", stub)

    assert ui._fmt_timestamp("2026-10-10T09:49:20.755126+00:00") == "10 Oct 2026, 09:49 UTC"
    stub.session_state["lang"] = "it"
    assert ui._fmt_timestamp("2026-02-04T05:01:26Z") == "4 feb 2026, 05:01 UTC"
    assert ui._fmt_timestamp("not-a-date") == "not-a-date"
    assert ui._fmt_timestamp(None) == "-"


class _Graph:
    def __init__(self, updates: list[dict], error: Exception | None = None) -> None:
        self.updates = updates
        self.error = error
        self.calls = 0

    def stream(self, _initial, stream_mode):
        self.calls += 1
        for update in self.updates:
            yield ("updates", update)
        if self.error:
            raise self.error


def test_planning_task_drains_stream_updates_and_completes() -> None:
    graph = _Graph([{"state": {"state_summary": "ready"}}])
    events: queue.Queue[object] = queue.Queue()
    stop_event = threading.Event()
    task = ui._PlanningTask(events=events, stop_event=stop_event)

    ui._run_stream(events, graph, {}, stop_event)
    ui._drain_planning_task(task)

    assert task.status == "done"
    assert task.result["state_summary"] == "ready"
    assert task.updates == [("state", {"state_summary": "ready"})]
    assert task.log == [("update", "state", {"state_summary": "ready"})]
    assert graph.calls == 1


def test_progress_label_rotates_with_the_wall_clock_tick(monkeypatch) -> None:
    monkeypatch.setattr(ui, "spinner_lines", lambda: ("one", "two", "three"))

    assert ui._progress_label(0) == "one..."
    assert ui._progress_label(1) == "two..."
    # Wraps around the phrase list.
    assert ui._progress_label(3) == "one..."


def test_progress_line_formats_lists_and_skips_unknown_phases(monkeypatch) -> None:
    monkeypatch.setattr(ui, "t", lambda key, **kw: key if not kw else key + repr(kw))

    line = ui._progress_line(
        {"node": "knowledge", "phase": "wiki_fetch", "titles": ["A", "B", "C", "D"]}
    )
    assert line.startswith("prog_wiki_fetch")
    assert "'titles': 'A, B, C\u2026'" in line
    assert ui._progress_line({"node": "knowledge", "phase": "not_a_phase"}) == ""


def test_drain_records_agent_starts_and_progress_events() -> None:
    task = ui._PlanningTask()

    task.events.put(ui._Progress({"node": "state", "phase": "start"}))
    task.events.put(ui._Progress({"node": "state", "phase": "objectives", "n": 3}))

    assert ui._drain_planning_task(task) is True
    assert task.log == [
        ("start", "state"),
        ("progress", {"node": "state", "phase": "objectives", "n": 3}),
    ]


def test_planning_task_stop_is_cooperative_and_does_not_start_new_work() -> None:
    graph = _Graph([{"state": {"state_summary": "should not run"}}])
    events: queue.Queue[object] = queue.Queue()
    stop_event = threading.Event()
    stop_event.set()
    task = ui._PlanningTask(events=events, stop_event=stop_event, status="stopping")

    ui._run_stream(events, graph, {}, stop_event)
    ui._drain_planning_task(task)

    assert task.status == "stopped"
    assert task.result == {}
    assert graph.calls == 0


def test_planning_task_reports_worker_errors() -> None:
    graph = _Graph([], error=RuntimeError("boom"))
    events: queue.Queue[object] = queue.Queue()
    stop_event = threading.Event()
    task = ui._PlanningTask(events=events, stop_event=stop_event)

    ui._run_stream(events, graph, {}, stop_event)
    ui._drain_planning_task(task)

    assert task.status == "error"
    assert task.error == "boom"


def test_drain_reports_whether_the_task_progressed() -> None:
    task = ui._PlanningTask()

    assert ui._drain_planning_task(task, wait=0.01) is False

    task.events.put({"state": {"state_summary": "ready"}})
    assert ui._drain_planning_task(task, wait=0.01) is True
    assert ui._drain_planning_task(task, wait=0.01) is False


def test_drain_keeps_the_message_it_waited_for() -> None:
    """A message fetched by the bounded wait must still reach the task."""
    task = ui._PlanningTask()
    task.events.put({"state": {"state_summary": "ready"}})

    assert ui._drain_planning_task(task, wait=1.0) is True
    assert task.updates == [("state", {"state_summary": "ready"})]


def test_planning_live_applies_streamed_events_until_done(monkeypatch) -> None:
    """The live loop drains the queue, replays events, and ticks the title."""
    stub = _StreamlitStub()
    events: queue.Queue[object] = queue.Queue()
    task = ui._PlanningTask(events=events, status="running")
    applied: list[tuple] = []
    outer_labels: list[str] = []
    drain = ui._drain_planning_task

    class _FakeStepper:
        def __init__(self, tick: int = 0) -> None:
            pass

        def start(self, node):
            pass

        def progress(self, payload):
            pass

        def finish(self, node, data):
            pass

        def set_outer(self, state, label):
            outer_labels.append(label)

    def _apply(_stepper, _task, cursor):
        applied.extend(_task.log[cursor:])
        return len(_task.log)

    def _wait(_task, wait=0.0):
        events.put(ui._Progress({"node": "state", "phase": "start"}))
        events.put(ui._Progress({"node": "state", "phase": "objectives", "n": 3}))
        events.put({"state": {"state_summary": "ready"}})
        events.put(None)  # the run finishes right after this update
        return drain(_task, wait=wait)

    monkeypatch.setattr(ui, "st", stub)
    monkeypatch.setattr(ui, "_PlanStepper", _FakeStepper)
    monkeypatch.setattr(ui, "_apply_log", _apply)
    monkeypatch.setattr(ui, "_drain_planning_task", _wait)
    monkeypatch.setattr(ui, "_IDLE_WAIT", 0.001)

    ui._planning_live(task)

    assert ("start", "state") in applied
    assert ("progress", {"node": "state", "phase": "objectives", "n": 3}) in applied
    assert ("update", "state", {"state_summary": "ready"}) in applied
    # Initial label plus the terminal (done) label were pushed to the box.
    assert outer_labels[0].endswith("...")
    assert len(outer_labels) >= 2
    assert stub.emptied >= 1


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (None, (False, True)),
        ("running", (True, False)),
        ("stopping", (True, True)),
        ("done", (False, True)),
        ("stopped", (False, True)),
        ("error", (False, True)),
    ],
)
def test_plan_controls_are_disabled_while_a_run_is_active(
    status: str | None, expected: tuple[bool, bool]
) -> None:
    task = ui._PlanningTask(status=status) if status else None

    assert ui._plan_controls_disabled(task, "gpt-4o-mini") == expected


def test_graph_streams_custom_start_and_agent_progress(monkeypatch) -> None:
    """The real graph emits a custom start per node plus agent progress events."""
    from app import graph as graph_module
    from app.agents import critic_agent, knowledge_agent, planning_agent, state_agent
    from app.domain import ClockTime, GameState, Goal, Plan, ValidationResult
    from app.progress import report

    monkeypatch.setattr(state_agent, "run", lambda _s: {"state_summary": "ready"})

    def _knowledge(_s):
        report({"node": "knowledge", "phase": "objectives", "n": 0})
        return {"relevant_objectives": []}

    monkeypatch.setattr(knowledge_agent, "run", _knowledge)
    monkeypatch.setattr(
        planning_agent,
        "run",
        lambda _s: {"plan": Plan(goal="g", steps=[])},
    )
    monkeypatch.setattr(
        critic_agent, "run", lambda _s: {"validation": ValidationResult(valid=True)}
    )

    app = graph_module.build_graph()
    initial = {"game_state": GameState(time=ClockTime(day=1, hour=8), location="Clock Town")}
    initial["goal"] = Goal(description="test")
    emitted = list(app.stream(initial, stream_mode=["updates", "custom"]))

    custom = [chunk for mode, chunk in emitted if mode == "custom"]
    assert {event["node"] for event in custom if event["phase"] == "start"} == {
        "memory",
        "state",
        "knowledge",
        "plan",
        "critic",
    }
    assert {"node": "knowledge", "phase": "objectives", "n": 0} in custom
    assert any(mode == "updates" for mode, _chunk in emitted)


def test_activity_md_highlights_the_current_event_and_dims_the_rest(monkeypatch) -> None:
    monkeypatch.setattr(ui, "t", lambda key, **kw: key)

    running = ui._activity_md(["one", "two"], running=True)
    assert running.startswith("**activity**")
    assert "- :gray[\u2713 one]" in running
    assert "- \u23f3 two" in running
    assert "---" not in running

    done = ui._activity_md(["one", "two"], running=False)
    assert "- :gray[\u2713 two]" in done
    assert done.rstrip().endswith("---")


class _Card:
    """Records the calls _step_* make on a status container."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def markdown(self, value: str, **_kwargs) -> None:
        self.calls.append(("markdown", value))

    def write(self, value: str, **_kwargs) -> None:
        self.calls.append(("write", value))

    def caption(self, value: str, **_kwargs) -> None:
        self.calls.append(("caption", value))

    def warning(self, value: str, **_kwargs) -> None:
        self.calls.append(("warning", value))

    def container(self, **_kwargs) -> _Card:
        return self


def test_step_plan_card_starts_with_result_label_without_agent_name(monkeypatch) -> None:
    from app.domain import ClockTime, Plan, PlanStep, TimeWindow

    monkeypatch.setattr(ui, "t", lambda key, **kw: key)
    monkeypatch.setattr(ui, "tr", lambda value: value)
    step = PlanStep(
        title="Talk to Anju",
        objective_ref="anju_talk",
        location="Stockpot Inn",
        window=TimeWindow(start=ClockTime(day=2, hour=9), end=ClockTime(day=2, hour=10)),
    )
    result = {
        "plan": Plan(goal="g", steps=[step]),
        "replan_attempts": 1,
        "plan_engine": "llm",
        "plan_model": "gpt-4o-mini",
    }
    card = _Card()

    ui._step_plan(card, result)

    assert card.calls[0] == ("markdown", "**result_plan**")
    rendered = "\n".join(value for _kind, value in card.calls)
    assert "agent_planning" not in rendered
    assert "1. Talk to Anju @ Stockpot Inn (`Day 2 - 09:00\u201310:00`)" in rendered


def test_step_label_carries_the_engine_badge_not_the_card(monkeypatch) -> None:
    monkeypatch.setattr(ui, "t", lambda key, **kw: key)
    label = ui._PlanStepper._step_label("knowledge", {"knowledge_engine": "rule-based"})
    assert label == "\u2713 agent_knowledge (rule-based)"


def test_step_critic_valid_does_not_add_a_second_check(monkeypatch) -> None:
    from app.domain import ValidationResult

    monkeypatch.setattr(ui, "t", lambda key, **kw: key)
    monkeypatch.setattr(ui, "tr", lambda value: value)
    card = _Card()

    ui._step_critic(card, {"validation": ValidationResult(valid=True)})

    assert ("markdown", "**result_critic**") in card.calls
    assert ("write", "plan_valid") in card.calls


def test_step_state_card_formats_fields_and_keeps_quest_progress(monkeypatch) -> None:
    from app.domain import ClockTime, GameState

    monkeypatch.setattr(ui, "t", lambda key, **kw: key)
    monkeypatch.setattr(ui, "tr", lambda value: value)
    gs = GameState(
        time=ClockTime(day=2, hour=8),
        location="Stockpot Inn",
        inventory=["Deku Leaf"],
        masks=["Kafei's Mask"],
    )
    card = _Card()

    ui._step_state(
        card,
        {
            "game_state": gs,
            "state_summary": "Stockpot Inn at Day 2 08:00.\nActive: Anju & Kafei.",
        },
    )

    assert card.calls[0] == ("markdown", "**result_state**")
    fields = card.calls[1]
    assert fields[0] == "markdown"
    assert fields[1].splitlines() == [
        "- **trace_where** Stockpot Inn",
        "- **trace_when** `Day 2 - 08:00`",
        "- **trace_items** Deku Leaf",
        "- **trace_masks** Kafei's Mask",
    ]
    assert ("caption", "Active: Anju & Kafei.") in card.calls


def test_progress_templates_style_model_query_and_titles(monkeypatch) -> None:
    from app.i18n import _STRINGS

    for lang in ("en", "it"):
        templates = _STRINGS[lang]
        assert "`{model}`" in templates["prog_llm"]
        assert '"*{query}*"' in templates["prog_wiki_search"]
        assert templates["prog_wiki_fetch"].endswith("*{titles}*")
        assert templates["prog_wiki_indexed"].endswith("*{pages}*")


def test_plan_controls_require_a_model_before_planning() -> None:
    assert ui._plan_controls_disabled(None, "  ") == (True, True)


def test_app_renders_headless_without_error() -> None:
    """The real Streamlit entry point boots and renders the main controls.

    Uses Streamlit's AppTest to execute ``main.py`` end to end (no provider
    needed to render); a regression here means the UI no longer starts.
    """
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    app_path = Path(__file__).resolve().parents[1] / "main.py"
    at = AppTest.from_file(str(app_path), default_timeout=60).run()

    labels = [button.label for button in at.button]
    assert not at.exception
    assert any("Termina Companion" in title.value for title in at.title)
    assert any("Pianifica" in label for label in labels)
    assert any(label == "Stop" for label in labels)
