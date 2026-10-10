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
    assert "2026-01-03T04:05:06Z" in rendered
    assert "rag_no_evidence" in rendered


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
        "state",
        "knowledge",
        "plan",
        "critic",
    }
    assert {"node": "knowledge", "phase": "objectives", "n": 0} in custom
    assert any(mode == "updates" for mode, _chunk in emitted)


def test_plan_controls_require_a_model_before_planning() -> None:
    assert ui._plan_controls_disabled(None, "  ") == (True, True)
