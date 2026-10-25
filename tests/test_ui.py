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

    def success(self, value: str, **_kwargs) -> None:
        self.calls.append(("success", value))

    def error(self, value: str, **_kwargs) -> None:
        self.calls.append(("error", value))

    def subheader(self, value: str, **_kwargs) -> None:
        self.calls.append(("subheader", value))

    def tabs(self, labels: list[str], **_kwargs) -> list[_Container]:
        return [_Container() for _label in labels]

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


def test_clock_helpers_keep_after_midnight_on_the_same_game_day(monkeypatch) -> None:
    """The UI maps early hours to 24-29 and marks them as after midnight."""
    from app.domain import ClockTime, TimeWindow

    monkeypatch.setattr(ui, "tr", lambda value: value)

    assert ui._internal_hour(6) == 6
    assert ui._internal_hour(23) == 23
    assert ui._internal_hour(0) == 24
    assert ui._internal_hour(5) == 29

    night = ClockTime(day=1, hour=26, minute=30)
    assert ui._fmt_clock(night) == "`Day 1 - 02:30 (+1)`"

    same_day = TimeWindow(
        start=ClockTime(day=1, hour=23, minute=30),
        end=ClockTime(day=1, hour=24, minute=30),
    )
    assert ui._fmt_window(same_day) == "Day 1 - 23:30\u201300:30 (+1)"
    assert ui._window_range(same_day) == "`Day 1 - 23:30`\u201300:30 (+1)"

    cross_day = TimeWindow(start=ClockTime(day=1, hour=25), end=ClockTime(day=2, hour=8))
    assert ui._fmt_window(cross_day) == "Day 1 - 01:00 (+1)\u2013Day 2 - 08:00"


def test_time_label_distinguishes_day_night_and_after_midnight(monkeypatch) -> None:
    """The dynamic caption names the selected part of the game day."""
    import datetime

    monkeypatch.setattr(ui, "t", lambda key, **kwargs: f"{key}:{kwargs['time']}")

    assert ui._time_label(1, datetime.time(6, 0)) == "time_day:06:00"
    assert ui._time_label(1, datetime.time(18, 0)) == "time_night:18:00"
    assert ui._time_label(1, datetime.time(2, 30)) == "time_after_midnight:02:30"


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
    assert task.timings == {}


def test_drain_records_the_duration_of_a_finished_agent() -> None:
    task = ui._PlanningTask()

    task.events.put(ui._Progress({"node": "state", "phase": "start"}))
    task.events.put({"state": {"state_summary": "ok"}})

    assert ui._drain_planning_task(task) is True
    assert 1 in task.timings
    assert task.timings[1] >= 0


def test_agent_registry_rebuilds_attempts_and_durations(monkeypatch) -> None:
    from app.domain import (
        ClockTime,
        GameState,
        Plan,
        PlanStep,
        TimeWindow,
        ValidationResult,
    )

    def _t(key: str, **kwargs) -> str:
        params = ",".join(f"{name}={value}" for name, value in kwargs.items())
        return f"{key}:{params}" if params else key

    monkeypatch.setattr(ui, "t", _t)
    monkeypatch.setattr(ui, "tr", lambda value: value)
    monkeypatch.setattr(ui, "tr_msg", lambda value: value)
    state = GameState(
        time=ClockTime(day=1, hour=8),
        location="Clock Town",
        masks=["Kafei's Mask"],
        inventory=["Room Key"],
    )
    step = PlanStep(
        title="Meet Anju",
        location="Stockpot Inn",
        window=TimeWindow(
            start=ClockTime(day=1, hour=10),
            end=ClockTime(day=1, hour=11),
        ),
    )
    plan = Plan(goal="Anju", steps=[step])
    task = ui._PlanningTask()
    task.log = [
        ("start", "state"),
        ("update", "state", {"game_state": state, "state_engine": "rule-based"}),
        ("start", "plan"),
        (
            "update",
            "plan",
            {"plan": plan, "replan_attempts": 1, "plan_engine": "llm", "plan_model": "m"},
        ),
        ("start", "critic"),
        ("update", "critic", {"validation": ValidationResult(valid=True)}),
        ("start", "plan"),
        (
            "update",
            "plan",
            {"plan": plan, "replan_attempts": 2, "plan_engine": "llm", "plan_model": "m"},
        ),
        ("start", "critic"),
        ("update", "critic", {"validation": ValidationResult(valid=True)}),
    ]
    task.timings = {1: 1.0, 3: 2.0, 5: 0.5, 7: 1.5, 9: 0.4}
    task.result = {"validation": ValidationResult(valid=True)}

    markup = ui._agent_registry_html(task)

    assert markup.count("<details") == 5
    assert "step_attempt:n=1,max=3" in markup
    assert "step_attempt:n=2,max=3" in markup
    assert ">1.0s<" in markup
    assert ">2.0s<" in markup


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

    assert ui._plan_controls_disabled(task) == expected


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
    assert label == "agent_knowledge (rule-based)"


def test_plan_step_label_uppercases_llm_and_code_formats_the_model(monkeypatch) -> None:
    monkeypatch.setattr(ui, "t", lambda key, **kw: key)
    label = ui._PlanStepper._step_label(
        "plan",
        {"plan_engine": "llm", "plan_model": "llama3.2", "replan_attempts": 1},
    )
    assert label == "agent_planning (LLM \u00b7 `llama3.2`) \u2014 step_attempt"


class _StepStatus:
    """Status stub that fails if opened as a context manager."""

    def __init__(self) -> None:
        self.updates: list[dict] = []

    def __enter__(self):
        raise AssertionError("a running step must not be opened as a context manager")

    def empty(self):
        return self

    def update(self, **kwargs) -> None:
        self.updates.append(kwargs)


class _OuterStatus:
    def __init__(self) -> None:
        self.created: list[tuple[str, _StepStatus]] = []

    def status(self, label: str, **_kwargs) -> _StepStatus:
        status = _StepStatus()
        self.created.append((label, status))
        return status


def test_start_keeps_the_step_running_until_it_finishes(monkeypatch) -> None:
    """A step created with ``with`` is auto-completed at once by Streamlit."""
    monkeypatch.setattr(ui, "t", lambda key, **kw: key)
    stepper = ui._PlanStepper.__new__(ui._PlanStepper)
    stepper.outer = _OuterStatus()
    stepper._open = {}

    stepper.start("state")

    label, status = stepper.outer.created[0]
    assert label == "agent_state"
    assert stepper._open["state"].status is status
    assert status.updates == []

    stepper.close_open()
    assert status.updates == [{"state": "complete"}]
    assert stepper._open == {}


def test_step_critic_valid_does_not_add_a_second_check(monkeypatch) -> None:
    from app.domain import ValidationResult

    monkeypatch.setattr(ui, "t", lambda key, **kw: key)
    monkeypatch.setattr(ui, "tr", lambda value: value)
    card = _Card()

    ui._step_critic(card, {"validation": ValidationResult(valid=True)})

    assert ("markdown", "**result_critic**") in card.calls
    assert ("write", "plan_valid") in card.calls


def _patch_result_renderers(monkeypatch) -> list:
    """Stub the plan-result sections so only the heading logic is exercised."""
    rendered_issues = []

    def _issue(_scope, issue, fallback="plan"):
        rendered_issues.append(issue)

    monkeypatch.setattr(ui, "_render_issue", _issue)
    for name in (
        "_render_plan",
        "_render_why",
        "_render_sources",
        "_render_rag_evidence",
        "_render_run_audit",
        "_render_trace_state",
        "_render_memory",
        "_render_trace_attempts",
        "_render_trace_issues",
    ):
        monkeypatch.setattr(ui, name, lambda *args, **kwargs: None)
    return rendered_issues


def test_failed_run_still_renders_the_last_completed_attempt(monkeypatch) -> None:
    """A failed re-plan must not hide the plan of the previous attempt."""
    from app.domain import ClockTime, GameState, ValidationIssue, ValidationResult

    stub = _StreamlitStub()
    monkeypatch.setattr(ui, "st", stub)
    monkeypatch.setattr(ui, "t", lambda key, **kwargs: key)
    monkeypatch.setattr(ui, "tr", lambda value: value)
    rendered_issues = _patch_result_renderers(monkeypatch)

    issue = ValidationIssue(severity="error", kind="time", message="late")
    task = ui._PlanningTask(
        status="error",
        result={
            "validation": ValidationResult(valid=False, issues=[issue]),
            "replan_attempts": 1,
            "relevant_objectives": [],
            "game_state": GameState(time=ClockTime(day=1, hour=6), location="Clock Town"),
        },
    )

    ui._render_planning_result(task, kb=None)

    rendered = "\n".join(value for _kind, value in stub.calls)
    assert ("subheader", "last_plan_title") in stub.calls
    assert "plan_last_attempt" in rendered
    assert any(kind == "markdown" and "verdict_fail_title" in value for kind, value in stub.calls)
    assert any(kind == "markdown" and "problems" in value for kind, value in stub.calls)
    assert rendered_issues == []


def test_invalid_plan_marks_the_failing_step_and_missing_items(monkeypatch) -> None:
    from app.domain import ClockTime, Plan, PlanStep, TimeWindow, ValidationIssue

    def _t(key: str, **kwargs) -> str:
        return f"{key}:{kwargs}" if kwargs else key

    stub = _StreamlitStub()
    monkeypatch.setattr(ui, "st", stub)
    monkeypatch.setattr(ui, "t", _t)
    monkeypatch.setattr(ui, "tr", lambda value: value)
    monkeypatch.setattr(ui, "tr_msg", lambda value: value)
    steps = [
        PlanStep(
            title=f"Step {index}",
            location="Clock Town",
            window=TimeWindow(
                start=ClockTime(day=1, hour=8 + index),
                end=ClockTime(day=1, hour=9 + index),
            ),
        )
        for index in (0, 1, 2)
    ]
    issues = [
        ValidationIssue(
            severity="error",
            step_idx=1,
            kind="item",
            message="Missing item(s): Rampino.",
        ),
        ValidationIssue(
            severity="error",
            step_idx=1,
            kind="mask",
            message="Missing mask(s): Garo's Mask.",
        ),
    ]

    ui._render_plan(Plan(goal="goal", steps=steps), issues=issues, show_numbers=True)

    markup = next(value for kind, value in stub.calls if kind == "markdown")
    assert markup.count("tc-step bad") == 1
    assert "plan_step_title" in markup
    assert "missing_requirement" in markup
    assert "Rampino" in markup
    assert "Garo" in markup


def test_failed_run_without_a_completed_attempt_renders_no_plan(monkeypatch) -> None:
    stub = _StreamlitStub()
    monkeypatch.setattr(ui, "st", stub)
    monkeypatch.setattr(ui, "t", lambda key, **kwargs: key)
    _patch_result_renderers(monkeypatch)

    ui._render_planning_result(ui._PlanningTask(status="error"), kb=None)

    assert stub.calls == []


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
    assert ui._plan_controls_disabled(None) == (False, True)


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
    assert any("TaIA" in block.value for block in at.markdown)
    assert any("Chiedi a TaIA" in label for label in labels)
    assert any(label == "Stop" for label in labels)


def test_inventory_multiselect_add_custom_item_and_keep_it_selected() -> None:
    """A typed custom item becomes a selected tag and clears the input.

    Runs the real entry point in English: with translated labels AppTest
    cannot match the selectbox options (pre-existing formatter mismatch).
    """
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    app_path = Path(__file__).resolve().parents[1] / "main.py"
    at = AppTest.from_file(str(app_path), default_timeout=60)
    at.session_state["lang"] = "en"
    at.run()
    assert not at.exception
    assert "Hookshot" in at.get_by_key("save_inventory").options

    at.text_input(key="save_inventory_new").set_value("Deku Leaf")
    at.run()
    at.button(key="save_inventory_add").click()
    at.run()

    assert not at.exception
    inventory = at.get_by_key("save_inventory")
    assert "Deku Leaf" in inventory.options
    assert inventory.value == ["Deku Leaf"]
    assert at.get_by_key("save_inventory_new").value == ""


def test_evaluation_tab_renders_the_sweep_controls() -> None:
    """The evaluation tab exposes the scenario picker and the run control."""
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from app.evaluation.scenarios import EVALUATION_SCENARIOS

    app_path = Path(__file__).resolve().parents[1] / "main.py"
    at = AppTest.from_file(str(app_path), default_timeout=60)
    at.session_state["lang"] = "en"
    at.run()

    assert not at.exception
    assert [tab.label for tab in at.tabs] == ["Play", "Evaluation"]
    picker = at.get_by_key("eval_scenarios")
    assert picker.value == [scenario.id for scenario in EVALUATION_SCENARIOS]
    assert at.get_by_key("eval_rag").value is True
    assert at.button(key="eval_run_button").disabled is False
    assert at.button(key="eval_stop_button").disabled is True


def test_evaluation_task_drains_results_and_completes() -> None:
    """The evaluation task collects every finished scenario and then closes."""
    from app.evaluation.models import ScenarioResult
    from app.evaluation.scenarios import SCENARIOS_BY_ID

    task = ui._EvaluationTask(total=1)
    task.events.put(
        (SCENARIOS_BY_ID["anju-kafei"], ScenarioResult(scenario_id="anju-kafei", passed=True))
    )
    task.events.put(None)

    assert ui._drain_evaluation_task(task) is True
    assert task.status == "done"
    assert [result.scenario_id for result in task.results] == ["anju-kafei"]
    assert task.current == "anju-kafei"


def test_evaluation_task_stop_is_cooperative() -> None:
    """A stop request ends the sweep as stopped, not as done."""
    task = ui._EvaluationTask(total=2)
    task.stop_event.set()
    task.events.put(None)

    ui._drain_evaluation_task(task)

    assert task.status == "stopped"
    assert task.results == []


def test_evaluation_task_reports_worker_errors() -> None:
    """A failing sweep is reported instead of swallowed."""
    task = ui._EvaluationTask(total=1)
    task.events.put(RuntimeError("boom"))
    task.events.put(None)

    ui._drain_evaluation_task(task)

    assert task.error == "boom"
    assert task.status == "error"


def test_sweep_timestamp_is_shown_without_the_iso_noise():
    """A stored sweep time renders as a readable date, not raw ISO."""
    assert ui._format_timestamp("2026-10-22T15:25:21+00:00") == "22/10/2026 15:25 UTC"
    # An unparsable value is shown unchanged instead of disappearing.
    assert ui._format_timestamp("yesterday") == "yesterday"


def test_evaluation_tab_renders_the_report_of_a_finished_sweep(tmp_path, monkeypatch) -> None:
    """A finished sweep shows the metrics, the table and the failed checks."""
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from app.evaluation.models import EvaluationIssue, ScenarioResult

    # The tab compares the report with the stored history: keep it empty so
    # the developer's own sweeps never leak into this test.
    monkeypatch.setenv("RAG_QDRANT_PATH", str(tmp_path / "cache" / "qdrant"))
    app_path = Path(__file__).resolve().parents[1] / "main.py"
    at = AppTest.from_file(str(app_path), default_timeout=60)
    at.session_state["lang"] = "en"
    at.run()
    assert not at.exception

    task = ui._EvaluationTask(total=2, status="done")
    task.results = [
        ScenarioResult(scenario_id="anju-kafei", passed=True, step_count=4, duration_s=12.4),
        ScenarioResult(
            scenario_id="deed-chain",
            passed=False,
            step_count=3,
            duration_s=9.1,
            issues=[
                EvaluationIssue(
                    severity="error",
                    kind="temporal_ordering",
                    message="Step 2 overlaps the previous step.",
                    step_idx=1,
                )
            ],
        ),
    ]
    at.session_state["_evaluation_task"] = task
    at.run()

    assert not at.exception
    metrics = {metric.label: metric.value for metric in at.metric}
    assert metrics["Pass rate"] == "50%"
    assert metrics["Passed"] == "1/2"
    assert metrics["Failed"] == "1"
    assert len(at.table) == 1
    assert [expander.label for expander in at.expander] == [
        "anju-kafei — PASS",
        "deed-chain — FAIL",
    ]


def test_evaluation_tab_flags_a_regression_against_the_stored_history(
    tmp_path, monkeypatch
) -> None:
    """A stored sweep that passed every scenario makes the new failure a regression."""
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from app.evaluation.models import EvaluationIssue, EvaluationReport, ScenarioResult
    from app.evaluation.storage import save_report

    monkeypatch.setenv("RAG_QDRANT_PATH", str(tmp_path / "cache" / "qdrant"))
    # The stored sweep becomes both the last report and the history entry the
    # tab compares against.
    save_report(
        EvaluationReport(
            results=[
                ScenarioResult(scenario_id="anju-kafei", passed=True),
                ScenarioResult(scenario_id="deed-chain", passed=True),
            ],
            rag_on=True,
            created_at="2026-10-20T09:00:00+00:00",
        )
    )

    app_path = Path(__file__).resolve().parents[1] / "main.py"
    at = AppTest.from_file(str(app_path), default_timeout=60)
    at.session_state["lang"] = "en"
    at.run()
    assert not at.exception

    task = ui._EvaluationTask(total=2, status="done")
    task.results = [
        ScenarioResult(scenario_id="anju-kafei", passed=True),
        ScenarioResult(
            scenario_id="deed-chain",
            passed=False,
            issues=[
                EvaluationIssue(
                    severity="error",
                    kind="temporal_ordering",
                    message="Step 2 overlaps the previous step.",
                )
            ],
        ),
    ]
    at.session_state["_evaluation_task"] = task
    at.run()

    assert not at.exception
    warnings = [warning.value for warning in at.warning]
    assert any(
        "Previous sweep of 20/10/2026 09:00 UTC" in warning
        and "2/2" in warning
        and "1/2" in warning
        for warning in warnings
    )
    # The scenario table plus the comparison table.
    assert len(at.table) == 2


def test_evaluation_run_error_never_shows_the_success_message(tmp_path, monkeypatch) -> None:
    """A crashed run shows the error only, never "no issues"."""
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from app.evaluation.models import ScenarioResult

    # The tab compares the report with the stored history: keep it empty.
    monkeypatch.setenv("RAG_QDRANT_PATH", str(tmp_path / "cache" / "qdrant"))
    app_path = Path(__file__).resolve().parents[1] / "main.py"
    at = AppTest.from_file(str(app_path), default_timeout=60)
    at.session_state["lang"] = "en"
    at.run()
    assert not at.exception

    task = ui._EvaluationTask(total=1, status="done")
    task.results = [
        ScenarioResult(
            scenario_id="anju-kafei",
            passed=False,
            step_count=0,
            duration_s=2.0,
            error="PlanningAgentError: LLM invocation failed",
        )
    ]
    at.session_state["_evaluation_task"] = task
    at.run()

    assert not at.exception
    assert not at.success
    assert any("LLM invocation failed" in error.value for error in at.error)


def test_evaluation_worker_saves_the_report(tmp_path, monkeypatch) -> None:
    """The sweep outcome reaches disk even when nobody drains the queue."""
    from app.evaluation.models import ScenarioResult
    from app.evaluation.scenarios import SCENARIOS_BY_ID
    from app.evaluation.storage import load_report

    monkeypatch.setenv("RAG_QDRANT_PATH", str(tmp_path / "cache" / "qdrant"))
    scenario = SCENARIOS_BY_ID["anju-kafei"]

    def _fake_run(scenarios, rag_on=True, on_progress=None, should_stop=None):
        """Emit one result per scenario without touching a model."""
        for item in scenarios:
            if on_progress is not None:
                on_progress(item, ScenarioResult(scenario_id=item.id, passed=True))
        return ui.EvaluationReport(results=[])

    monkeypatch.setattr(ui, "run_scenarios", _fake_run)
    task = ui._EvaluationTask(total=1)
    ui._run_evaluation([scenario], rag_on=False, task=task)

    saved = load_report()
    assert saved is not None
    assert [result.scenario_id for result in saved.results] == ["anju-kafei"]
    assert saved.passed == 1


def test_evaluation_worker_skips_an_empty_sweep(tmp_path, monkeypatch) -> None:
    """A sweep that produced nothing never overwrites a good report."""
    from app.evaluation.models import ScenarioResult
    from app.evaluation.scenarios import SCENARIOS_BY_ID
    from app.evaluation.storage import load_report, save_report

    monkeypatch.setenv("RAG_QDRANT_PATH", str(tmp_path / "cache" / "qdrant"))
    save_report(
        ui.EvaluationReport(results=[ScenarioResult(scenario_id="anju-kafei", passed=True)])
    )

    def _failing_run(scenarios, rag_on=True, on_progress=None, should_stop=None):
        """Raise before producing any result, like an unconfigured LLM."""
        raise RuntimeError("LLM not configured")

    monkeypatch.setattr(ui, "run_scenarios", _failing_run)
    task = ui._EvaluationTask(total=1)
    ui._run_evaluation([SCENARIOS_BY_ID["anju-kafei"]], rag_on=False, task=task)

    saved = load_report()
    assert saved is not None
    assert [result.scenario_id for result in saved.results] == ["anju-kafei"]


def test_evaluation_tab_loads_the_saved_report(tmp_path, monkeypatch) -> None:
    """The evaluation tab restores the checks persisted by the last sweep."""
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from app.evaluation.models import EvaluationIssue, ScenarioResult
    from app.evaluation.storage import save_report

    monkeypatch.setenv("RAG_QDRANT_PATH", str(tmp_path / "cache" / "qdrant"))
    save_report(
        ui.EvaluationReport(
            results=[
                ScenarioResult(
                    scenario_id="anju-kafei", passed=True, step_count=4, duration_s=12.4
                ),
                ScenarioResult(
                    scenario_id="deed-chain",
                    passed=False,
                    step_count=3,
                    duration_s=9.1,
                    issues=[
                        EvaluationIssue(
                            severity="error",
                            kind="temporal_ordering",
                            message="Step 2 overlaps the previous step.",
                            step_idx=1,
                        )
                    ],
                ),
            ]
        ),
        history=False,
    )

    app_path = Path(__file__).resolve().parents[1] / "main.py"
    at = AppTest.from_file(str(app_path), default_timeout=60)
    at.session_state["lang"] = "en"
    at.run()
    assert not at.exception

    at.button(key="eval_load_button").click()
    at.run()

    assert not at.exception
    metrics = {metric.label: metric.value for metric in at.metric}
    assert metrics["Pass rate"] == "50%"
    assert metrics["Passed"] == "1/2"
    assert len(at.table) == 1
    assert [expander.label for expander in at.expander] == [
        "anju-kafei — PASS",
        "deed-chain — FAIL",
    ]


def test_evaluation_tab_reports_a_missing_saved_report(tmp_path, monkeypatch) -> None:
    """Loading with nothing on disk says so instead of failing."""
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("RAG_QDRANT_PATH", str(tmp_path / "cache" / "qdrant"))

    app_path = Path(__file__).resolve().parents[1] / "main.py"
    at = AppTest.from_file(str(app_path), default_timeout=60)
    at.session_state["lang"] = "en"
    at.run()
    assert not at.exception

    at.button(key="eval_load_button").click()
    at.run()

    assert not at.exception
    assert any("No saved evaluation report yet." in info.value for info in at.info)
    assert not at.table


def test_plan_timeline_escapes_text_and_marks_the_last_step(monkeypatch) -> None:
    """The timeline never injects plan text as HTML and flags the final step."""
    from app.domain import ClockTime, Plan, PlanStep, TimeWindow

    stub = _StreamlitStub()
    monkeypatch.setattr(ui, "st", stub)
    monkeypatch.setattr(ui, "t", lambda key, **kwargs: key)
    monkeypatch.setattr(ui, "tr", lambda value: value)

    plan = Plan(
        goal="g",
        steps=[
            PlanStep(
                title="<b>First</b>",
                location="Clock Town",
                window=TimeWindow(
                    start=ClockTime(day=1, hour=8),
                    end=ClockTime(day=1, hour=9),
                ),
            ),
            PlanStep(
                title="Last",
                location="Stockpot Inn",
                window=TimeWindow(
                    start=ClockTime(day=1, hour=9),
                    end=ClockTime(day=1, hour=10),
                ),
            ),
        ],
    )

    ui._render_plan(plan)

    markup = "\n".join(value for kind, value in stub.calls if kind == "markdown")
    assert "&lt;b&gt;First&lt;/b&gt;" in markup
    assert "<b>First</b>" not in markup
    assert markup.count('class="tc-step-card"') == 2
    assert 'class="tc-step last"' in markup
