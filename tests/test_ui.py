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
            yield update
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
    assert graph.calls == 1


def test_planning_progress_label_advances_only_on_new_agent_updates(monkeypatch) -> None:
    monkeypatch.setattr(ui, "spinner_lines", lambda: ("one", "two", "three"))
    graph = _Graph(
        [
            {"state": {"state_summary": "a"}},
            {"knowledge": {"relevant_objectives": []}},
        ]
    )
    events: queue.Queue[object] = queue.Queue()
    stop_event = threading.Event()
    task = ui._PlanningTask(events=events, stop_event=stop_event)

    ui._run_stream(events, graph, {}, stop_event)
    first = ui._progress_label(task)
    assert first == "one..."

    # Re-rendering without new work must not move the label.
    assert ui._progress_label(task) == first

    ui._drain_planning_task(task)
    second = ui._progress_label(task)
    assert second == "three..."

    # Further re-renders of the same state stay stable.
    assert ui._progress_label(task) == second
    assert task.spinner_index == 2


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
    assert task.spinner_index == 1


def test_planning_live_redraws_only_when_the_run_advances(monkeypatch) -> None:
    """The live loop paints once, then once per update, never on idle polls."""
    stub = _StreamlitStub()
    paints: list[str] = []
    events: queue.Queue[object] = queue.Queue()
    task = ui._PlanningTask(events=events, status="running")
    drain = ui._drain_planning_task
    polls = {"n": 0}

    def _wait(_task, wait=0.0):
        polls["n"] += 1
        if polls["n"] == 1:
            return False  # idle poll: yield, but do not redraw
        events.put({"state": {"state_summary": "ready"}})
        events.put(None)  # the run finishes right after this update
        return drain(_task, wait=wait)

    monkeypatch.setattr(ui, "st", stub)
    monkeypatch.setattr(ui, "_render_planning_progress", lambda t: paints.append(t.status))
    monkeypatch.setattr(ui, "_drain_planning_task", _wait)
    monkeypatch.setattr(ui, "_IDLE_WAIT", 0.001)

    ui._planning_live(task)

    # One initial paint plus one for the drained update, and the run is over.
    assert paints == ["running", "done"]
    assert polls["n"] == 2
    # The idle poll only emitted the invisible yield point.
    assert stub.emptied == 1


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


def test_plan_controls_require_a_model_before_planning() -> None:
    assert ui._plan_controls_disabled(None, "  ") == (True, True)
