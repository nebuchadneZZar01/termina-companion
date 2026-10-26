"""Focused Streamlit rendering and planning-task lifecycle tests."""

from __future__ import annotations

import queue
import threading

import pytest

from app.rag.models import IndexedSource, SourceMetadata
from app.settings import RAGSettings, Settings
from app.ui import (
    evaluation_view,
    formatting,
    issues,
    page,
    plan_view,
    registry,
    sidebar,
    tasks,
    theme,
    trace_view,
)


class _Container:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Placeholder:
    """Stand-in for the empty placeholders of the live loop."""

    def __init__(self, stub: _StreamlitStub) -> None:
        self.stub = stub

    def empty(self) -> _Placeholder:
        self.stub.emptied += 1
        return self

    def markdown(self, value: str, **_kwargs) -> None:
        self.stub.live_markdowns.append(value)


class _StreamlitStub:
    def __init__(self) -> None:
        self.session_state: dict[str, str] = {}
        self.calls: list[tuple[str, str]] = []
        self.live_markdowns: list[str] = []
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
    monkeypatch.setattr(plan_view, "st", stub)
    monkeypatch.setattr(
        plan_view, "t", lambda key, **kwargs: key.format(**kwargs) if kwargs else key
    )
    monkeypatch.setattr(plan_view, "tr", lambda value: value)

    plan_view._render_rag_evidence(
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
    monkeypatch.setattr(formatting, "st", stub)

    assert formatting._fmt_timestamp("2026-10-10T09:49:20.755126+00:00") == "10 Oct 2026, 09:49 UTC"
    stub.session_state["lang"] = "it"
    assert formatting._fmt_timestamp("2026-02-04T05:01:26Z") == "4 feb 2026, 05:01 UTC"
    assert formatting._fmt_timestamp("not-a-date") == "not-a-date"
    assert formatting._fmt_timestamp(None) == "-"


def test_clock_helpers_keep_after_midnight_on_the_same_game_day(monkeypatch) -> None:
    """The UI maps early hours to 24-29 and marks them as after midnight."""
    from app.domain import ClockTime, TimeWindow

    monkeypatch.setattr(formatting, "tr", lambda value: value)

    assert formatting._internal_hour(6) == 6
    assert formatting._internal_hour(23) == 23
    assert formatting._internal_hour(0) == 24
    assert formatting._internal_hour(5) == 29

    night = ClockTime(day=1, hour=26, minute=30)
    assert formatting._fmt_clock(night) == "`Day 1 - 02:30 (+1)`"

    same_day = TimeWindow(
        start=ClockTime(day=1, hour=23, minute=30),
        end=ClockTime(day=1, hour=24, minute=30),
    )
    assert formatting._fmt_window(same_day) == "Day 1 - 23:30\u201300:30 (+1)"
    assert formatting._window_range(same_day) == "`Day 1 - 23:30`\u201300:30 (+1)"

    cross_day = TimeWindow(start=ClockTime(day=1, hour=25), end=ClockTime(day=2, hour=8))
    assert formatting._fmt_window(cross_day) == "Day 1 - 01:00 (+1)\u2013Day 2 - 08:00"


def test_time_label_distinguishes_day_night_and_after_midnight(monkeypatch) -> None:
    """The dynamic caption names the selected part of the game day."""
    import datetime

    monkeypatch.setattr(formatting, "t", lambda key, **kwargs: f"{key}:{kwargs['time']}")

    assert formatting._time_label(1, datetime.time(6, 0)) == "time_day:06:00"
    assert formatting._time_label(1, datetime.time(18, 0)) == "time_night:18:00"
    assert formatting._time_label(1, datetime.time(2, 30)) == "time_after_midnight:02:30"


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
    task = tasks._PlanningTask(events=events, stop_event=stop_event)

    tasks._run_stream(events, graph, {}, stop_event)
    tasks._drain_planning_task(task)

    assert task.status == "done"
    assert task.result["state_summary"] == "ready"
    assert task.updates == [("state", {"state_summary": "ready"})]
    assert task.log == [("update", "state", {"state_summary": "ready"})]
    assert graph.calls == 1


def test_progress_label_rotates_with_the_wall_clock_tick(monkeypatch) -> None:
    monkeypatch.setattr(registry, "spinner_lines", lambda: ("one", "two", "three"))

    assert registry._progress_label(0) == "one..."
    assert registry._progress_label(1) == "two..."
    # Wraps around the phrase list.
    assert registry._progress_label(3) == "one..."


def test_apply_pending_load_sets_widget_keys_before_render(monkeypatch) -> None:
    from app.domain import ClockTime
    from app.save import SaveSnapshot

    stub = _StreamlitStub()
    monkeypatch.setattr(sidebar, "st", stub)
    snapshot = SaveSnapshot(
        time=ClockTime(day=2, hour=26, minute=30),
        location="Stock Pot Inn",
        masks=["Kafei's Mask"],
        inventory=["Room Key"],
        quest_progress=["Anju & Kafei"],
        goal="Help Anju",
        migration_warning="migrated",
    )
    stub.session_state["_load_pending"] = snapshot

    sidebar._apply_pending_load()

    assert "_load_pending" not in stub.session_state
    assert stub.session_state["save_day"] == 2
    assert stub.session_state["save_time"].hour == 2
    assert stub.session_state["save_time"].minute == 30
    assert stub.session_state["save_location"] == "Stock Pot Inn"
    assert stub.session_state["save_masks"] == ["Kafei's Mask"]
    assert stub.session_state["save_inventory"] == ["Room Key"]
    assert stub.session_state["save_quests"] == ["Anju & Kafei"]
    assert stub.session_state["save_goal"] == "Help Anju"
    assert stub.session_state["_save_warning"] == "migrated"
    assert stub.session_state["_load_ok"] is True


def test_progress_line_formats_lists_and_skips_unknown_phases(monkeypatch) -> None:
    monkeypatch.setattr(registry, "t", lambda key, **kw: key if not kw else key + repr(kw))

    line = registry._progress_line(
        {"node": "knowledge", "phase": "wiki_fetch", "titles": ["A", "B", "C", "D"]}
    )
    assert line.startswith("prog_wiki_fetch")
    assert "'titles': 'A, B, C\u2026'" in line
    assert registry._progress_line({"node": "knowledge", "phase": "not_a_phase"}) == ""


def test_drain_records_agent_starts_and_progress_events() -> None:
    task = tasks._PlanningTask()

    task.events.put(tasks._Progress({"node": "state", "phase": "start"}))
    task.events.put(tasks._Progress({"node": "state", "phase": "objectives", "n": 3}))

    assert tasks._drain_planning_task(task) is True
    assert task.log == [
        ("start", "state"),
        ("progress", {"node": "state", "phase": "objectives", "n": 3}),
    ]
    assert task.timings == {}


def test_drain_records_the_duration_of_a_finished_agent() -> None:
    task = tasks._PlanningTask()

    task.events.put(tasks._Progress({"node": "state", "phase": "start"}))
    task.events.put({"state": {"state_summary": "ok"}})

    assert tasks._drain_planning_task(task) is True
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

    monkeypatch.setattr(registry, "t", _t)
    monkeypatch.setattr(registry, "tr", lambda value: value)
    monkeypatch.setattr(issues, "tr_msg", lambda value: value)
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
    task = tasks._PlanningTask()
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

    markup = registry._agent_registry_html(task)

    assert markup.count("<details") == 5
    assert "step_attempt:n=1,max=3" in markup
    assert "step_attempt:n=2,max=3" in markup
    assert ">1.0s<" in markup
    assert ">2.0s<" in markup
    assert "<code>m</code>" in markup


def test_planning_task_stop_is_cooperative_and_does_not_start_new_work() -> None:
    graph = _Graph([{"state": {"state_summary": "should not run"}}])
    events: queue.Queue[object] = queue.Queue()
    stop_event = threading.Event()
    stop_event.set()
    task = tasks._PlanningTask(events=events, stop_event=stop_event, status="stopping")

    tasks._run_stream(events, graph, {}, stop_event)
    tasks._drain_planning_task(task)

    assert task.status == "stopped"
    assert task.result == {}
    assert graph.calls == 0


def test_planning_task_reports_worker_errors() -> None:
    graph = _Graph([], error=RuntimeError("boom"))
    events: queue.Queue[object] = queue.Queue()
    stop_event = threading.Event()
    task = tasks._PlanningTask(events=events, stop_event=stop_event)

    tasks._run_stream(events, graph, {}, stop_event)
    tasks._drain_planning_task(task)

    assert task.status == "error"
    assert task.error == "boom"


def test_drain_reports_whether_the_task_progressed() -> None:
    task = tasks._PlanningTask()

    assert tasks._drain_planning_task(task, wait=0.01) is False

    task.events.put({"state": {"state_summary": "ready"}})
    assert tasks._drain_planning_task(task, wait=0.01) is True
    assert tasks._drain_planning_task(task, wait=0.01) is False


def test_drain_keeps_the_message_it_waited_for() -> None:
    """A message fetched by the bounded wait must still reach the task."""
    task = tasks._PlanningTask()
    task.events.put({"state": {"state_summary": "ready"}})

    assert tasks._drain_planning_task(task, wait=1.0) is True
    assert task.updates == [("state", {"state_summary": "ready"})]


def test_planning_live_draws_the_html_registry_with_progress(monkeypatch) -> None:
    """The live loop paints the same registry markup used after the run."""
    stub = _StreamlitStub()
    events: queue.Queue[object] = queue.Queue()
    task = tasks._PlanningTask(events=events, status="running")
    drain = tasks._drain_planning_task
    calls = {"n": 0}

    def _wait(_task, wait=0.0):
        calls["n"] += 1
        if calls["n"] == 1:
            events.put(tasks._Progress({"node": "state", "phase": "start"}))
            events.put(tasks._Progress({"node": "state", "phase": "objectives", "n": 3}))
        else:
            events.put({"state": {"state_summary": "ready"}})
            events.put(None)
        return drain(_task, wait=wait)

    monkeypatch.setattr(registry, "st", stub)
    monkeypatch.setattr(registry, "t", lambda key, **kwargs: key)
    monkeypatch.setattr(registry, "_drain_planning_task", _wait)
    monkeypatch.setattr(registry, "_IDLE_WAIT", 0.001)

    registry._planning_live(task)

    assert ("start", "state") in task.log
    assert any("tc-live-title" in value for value in stub.live_markdowns)
    running = next(value for value in stub.live_markdowns if "tc-reg-activity" in value)
    assert 'class="tc-reg running"' in running
    assert " open>" in running
    assert any("prog_objectives" in value for value in stub.live_markdowns)
    assert any("agent_registry_live_hint" in value for value in stub.live_markdowns)
    assert stub.emptied >= 2


def test_registry_activity_highlights_the_current_event(monkeypatch) -> None:
    monkeypatch.setattr(registry, "t", lambda key, **kwargs: key)

    markup = registry._registry_activity_html(
        [
            {"node": "knowledge", "phase": "objectives", "n": 2},
            {"node": "plan", "phase": "llm", "model": "gpt"},
        ],
        running=True,
    )

    assert 'class="current"' in markup
    assert "prog_objectives" in markup
    assert "prog_llm" in markup
    assert markup.count("\u23f3") == 1


def test_registry_activity_renders_the_model_as_code(monkeypatch) -> None:
    monkeypatch.setattr(
        registry,
        "t",
        lambda key, **kwargs: (
            "Calling `{model}` (attempt {attempt})" if key == "prog_llm" else key
        ).format(**kwargs),
    )
    monkeypatch.setattr(registry, "tr", lambda value: value)

    markup = registry._registry_activity_html(
        [{"node": "plan", "phase": "llm", "model": "gpt-4o", "attempt": 1}],
        running=False,
    )

    assert "<code>gpt-4o</code>" in markup


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
    task = tasks._PlanningTask(status=status) if status else None

    assert tasks._plan_controls_disabled(task) == expected


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


def _patch_result_renderers(monkeypatch) -> list:
    """Stub the plan-result sections so only the heading logic is exercised."""
    rendered_issues = []

    def _issue(_scope, issue, fallback="plan"):
        rendered_issues.append(issue)

    monkeypatch.setattr(issues, "_render_issue", _issue)
    for name in (
        "_render_plan",
        "_render_why",
        "_render_sources",
        "_render_rag_evidence",
    ):
        monkeypatch.setattr(plan_view, name, lambda *args, **kwargs: None)
    for name in (
        "_render_run_audit",
        "_render_trace_state",
        "_render_memory",
        "_render_trace_attempts",
        "_render_trace_issues",
    ):
        monkeypatch.setattr(trace_view, name, lambda *args, **kwargs: None)
    return rendered_issues


def test_failed_run_still_renders_the_last_completed_attempt(monkeypatch) -> None:
    """A failed re-plan must not hide the plan of the previous attempt."""
    from app.domain import ClockTime, GameState, ValidationIssue, ValidationResult

    stub = _StreamlitStub()
    monkeypatch.setattr(plan_view, "st", stub)
    monkeypatch.setattr(formatting, "st", stub)
    monkeypatch.setattr(theme, "st", stub)
    monkeypatch.setattr(plan_view, "t", lambda key, **kwargs: key)
    monkeypatch.setattr(plan_view, "tr", lambda value: value)
    rendered_issues = _patch_result_renderers(monkeypatch)

    issue = ValidationIssue(severity="error", kind="time", message="late")
    task = tasks._PlanningTask(
        status="error",
        result={
            "validation": ValidationResult(valid=False, issues=[issue]),
            "replan_attempts": 1,
            "relevant_objectives": [],
            "game_state": GameState(time=ClockTime(day=1, hour=6), location="Clock Town"),
        },
    )

    plan_view._render_planning_result(task, kb=None)

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
    monkeypatch.setattr(plan_view, "st", stub)
    monkeypatch.setattr(formatting, "st", stub)
    monkeypatch.setattr(theme, "st", stub)
    monkeypatch.setattr(plan_view, "t", _t)
    monkeypatch.setattr(plan_view, "tr", lambda value: value)
    monkeypatch.setattr(issues, "tr_msg", lambda value: value)
    monkeypatch.setattr(issues, "t", _t)
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
    issue_list = [
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

    plan_view._render_plan(Plan(goal="goal", steps=steps), issues=issue_list, show_numbers=True)

    markup = next(value for kind, value in stub.calls if kind == "markdown")
    assert markup.count("tc-step bad") == 1
    assert "plan_step_title" in markup
    assert "missing_requirement" in markup
    assert 'class="tc-item">Rampino' in markup
    assert 'class="tc-mask">Garo' in markup


def test_critic_tables_and_missing_chips_style_entities(monkeypatch) -> None:
    from app.data.mock_knowledge import build_default_knowledge
    from app.domain import ValidationIssue, ValidationResult

    monkeypatch.setattr(issues, "t", lambda key, **kwargs: f"{key}:{kwargs}" if kwargs else key)
    monkeypatch.setattr(issues, "tr", lambda value: value)
    monkeypatch.setattr(issues, "tr_msg", lambda value: value)

    issue_list = [
        ValidationIssue(
            severity="error", step_idx=0, kind="item", message="Missing item(s): Room Key."
        ),
        ValidationIssue(
            severity="error",
            step_idx=1,
            kind="mask",
            message="Missing mask(s): Kafei's Mask.",
        ),
    ]
    entities = issues._entity_index(build_default_knowledge())

    table = issues._issues_table_html(issue_list, entities=entities)
    assert 'class="tc-item">Room Key' in table
    assert 'class="tc-mask">Kafei' in table

    body = registry._registry_critic_body(
        {"validation": ValidationResult(valid=False, issues=issue_list)}, entities
    )
    assert 'class="tc-item">Room Key' in body
    assert 'class="tc-mask">Kafei' in body

    chips = issues._missing_chips_html(issue_list, prefix=True)
    assert 'class="tc-item">Room Key' in chips
    assert 'class="tc-mask">Kafei' in chips


def test_invalid_plan_renders_every_step(monkeypatch) -> None:
    from app.domain import ClockTime, Plan, PlanStep, TimeWindow, ValidationIssue

    stub = _StreamlitStub()
    monkeypatch.setattr(plan_view, "st", stub)
    monkeypatch.setattr(formatting, "st", stub)
    monkeypatch.setattr(theme, "st", stub)
    monkeypatch.setattr(plan_view, "t", lambda key, **kwargs: f"{key}:{kwargs}")
    monkeypatch.setattr(plan_view, "tr", lambda value: value)
    steps = [
        PlanStep(
            title=f"Step {index}",
            location="Clock Town",
            window=TimeWindow(
                start=ClockTime(day=1, hour=8 + index),
                end=ClockTime(day=1, hour=9 + index),
            ),
        )
        for index in range(5)
    ]
    issue = ValidationIssue(
        severity="error",
        step_idx=2,
        kind="item",
        message="Missing item(s): Rampino.",
    )

    plan_view._render_last_plan(Plan(goal="goal", steps=steps), [issue])

    markup = next(
        value for kind, value in stub.calls if kind == "markdown" and "tc-timeline" in value
    )
    assert markup.count('class="tc-step-time"') == 5
    assert 'class="tc-step last"' in markup
    assert 'class="tc-step last ok"' not in markup
    for index in range(5):
        assert f"Step {index}" in markup


def test_plan_details_keep_every_step_field(monkeypatch) -> None:
    from app.domain import ClockTime, Plan, PlanStep, TimeWindow

    stub = _StreamlitStub()
    monkeypatch.setattr(plan_view, "st", stub)
    monkeypatch.setattr(formatting, "st", stub)
    monkeypatch.setattr(theme, "st", stub)
    monkeypatch.setattr(formatting, "st", stub)
    monkeypatch.setattr(theme, "st", stub)
    monkeypatch.setattr(plan_view, "t", lambda key, **kwargs: f"{key}:{kwargs}")
    monkeypatch.setattr(plan_view, "tr", lambda value: value)

    plan = Plan(
        goal="goal",
        steps=[
            PlanStep(
                title="Ottieni la Maschera di Kafei",
                location="Stockpot Inn",
                window=TimeWindow(
                    start=ClockTime(day=1, hour=10),
                    end=ClockTime(day=1, hour=11),
                ),
                requires_items=["Room Key"],
                requires_masks=["Kafei's Mask"],
                depends_on=[0],
                actions=["Parla con Anju", "Apri la porta"],
            )
        ],
    )

    plan_view._render_why(plan)

    markup = next(value for kind, value in stub.calls if kind == "markdown")
    for expected in (
        "Ottieni la Maschera di Kafei",
        "Room Key",
        "Kafei",
        "depends_on",
        "Parla con Anju",
        "Apri la porta",
    ):
        assert expected in markup


def test_semantic_entity_styles_are_shared_by_state_knowledge_and_plan(
    monkeypatch,
) -> None:
    from app.data.mock_knowledge import build_default_knowledge
    from app.domain import ClockTime, GameState, Plan, PlanStep, TimeWindow

    stub = _StreamlitStub()
    monkeypatch.setattr(formatting, "st", stub)
    monkeypatch.setattr(theme, "st", stub)
    monkeypatch.setattr(plan_view, "st", stub)
    monkeypatch.setattr(formatting, "t", lambda key, **kwargs: f"{key}:{kwargs}")
    monkeypatch.setattr(formatting, "tr", lambda value: value)

    kb = build_default_knowledge()
    index = formatting._entity_index(kb)
    kinds = index[1]
    assert kinds["sun's mask"] == "mask"
    assert kinds["room key"] == "item"
    assert kinds["stockpot inn"] == "place"

    state = GameState(
        time=ClockTime(day=1, hour=6),
        location="Stockpot Inn",
        inventory=["Room Key"],
        masks=["Kafei's Mask"],
    )
    state_html = trace_view._state_fields_html(state)
    assert 'class="tc-place">Stockpot Inn' in state_html
    assert 'class="tc-item">Room Key' in state_html
    assert 'class="tc-mask">Kafei' in state_html

    objective = next(o for o in kb.all_objectives if "Kafei's Mask" in o.title)
    knowledge_html = registry._registry_knowledge_body({"relevant_objectives": [objective]}, index)
    assert 'class="tc-mask">Kafei' in knowledge_html

    plan = Plan(
        goal="goal",
        steps=[
            PlanStep(
                title="Get Kafei's Mask from Madame Aroma",
                location="Stockpot Inn",
                window=TimeWindow(
                    start=ClockTime(day=1, hour=10),
                    end=ClockTime(day=1, hour=11),
                ),
                requires_items=["Room Key"],
                requires_masks=["Kafei's Mask"],
            )
        ],
    )
    plan_view._render_plan(plan, kb=kb)
    markup = next(value for kind, value in stub.calls if kind == "markdown")
    assert 'class="tc-place">Stockpot Inn' in markup
    assert 'class="tc-item">Room Key' in markup
    assert 'class="tc-mask">Kafei' in markup

    plan_view._render_why(plan, kb=kb)
    why_markup = next(
        value for kind, value in stub.calls if kind == "markdown" and "tc-detail-card" in value
    )
    assert 'class="tc-item">Room Key' in why_markup
    assert 'class="tc-mask">Kafei' in why_markup


def test_fairy_greeting_accepts_a_custom_message() -> None:
    import datetime

    when = datetime.time(6, 0)
    play = formatting._fairy_html(1, when)
    evaluation = formatting._fairy_html(1, when, text="Prova generale")

    assert "Prova generale" in evaluation
    assert 'id="taiaw-play"' in play
    assert 'id="taiaw-eval"' in evaluation
    assert "url(#taiaw-play)" in play
    assert "url(#taiaw-eval)" in evaluation


def test_favicon_asset_is_available() -> None:
    assert page._FAVICON_PATH.is_file()
    markup = page._FAVICON_PATH.read_text(encoding="utf-8")
    assert markup.lstrip().startswith("<svg")
    assert 'viewBox="0 0 64 64"' in markup


def test_failure_breakdown_handles_empty_and_wrapping_kinds(monkeypatch) -> None:
    monkeypatch.setattr(evaluation_view, "t", lambda key, **kwargs: key)

    empty = evaluation_view._failure_breakdown_html({})
    many = evaluation_view._failure_breakdown_html({"run_error": 1, "temporal_ordering": 2})

    assert "tc-failure-empty" in empty
    assert "<b>1</b> kind_run_error" in many
    assert "<b>2</b> kind_temporal_ordering" in many


def test_failed_run_without_a_completed_attempt_renders_no_plan(monkeypatch) -> None:
    stub = _StreamlitStub()
    monkeypatch.setattr(plan_view, "st", stub)
    monkeypatch.setattr(formatting, "st", stub)
    monkeypatch.setattr(theme, "st", stub)
    monkeypatch.setattr(plan_view, "t", lambda key, **kwargs: key)
    _patch_result_renderers(monkeypatch)

    plan_view._render_planning_result(tasks._PlanningTask(status="error"), kb=None)

    assert stub.calls == []


def test_progress_templates_style_model_query_and_titles(monkeypatch) -> None:
    from app.i18n import _STRINGS

    for lang in ("en", "it"):
        templates = _STRINGS[lang]
        assert "`{model}`" in templates["prog_llm"]
        assert '"*{query}*"' in templates["prog_wiki_search"]
        assert templates["prog_wiki_fetch"].endswith("*{titles}*")
        assert templates["prog_wiki_indexed"].endswith("*{pages}*")


def test_plan_controls_require_a_model_before_planning() -> None:
    assert tasks._plan_controls_disabled(None) == (False, True)


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

    task = tasks._EvaluationTask(total=1)
    task.events.put(
        (SCENARIOS_BY_ID["anju-kafei"], ScenarioResult(scenario_id="anju-kafei", passed=True))
    )
    task.events.put(None)

    assert tasks._drain_evaluation_task(task) is True
    assert task.status == "done"
    assert [result.scenario_id for result in task.results] == ["anju-kafei"]
    assert task.current == "anju-kafei"


def test_evaluation_task_stop_is_cooperative() -> None:
    """A stop request ends the sweep as stopped, not as done."""
    task = tasks._EvaluationTask(total=2)
    task.stop_event.set()
    task.events.put(None)

    tasks._drain_evaluation_task(task)

    assert task.status == "stopped"
    assert task.results == []


def test_evaluation_task_reports_worker_errors() -> None:
    """A failing sweep is reported instead of swallowed."""
    task = tasks._EvaluationTask(total=1)
    task.events.put(RuntimeError("boom"))
    task.events.put(None)

    tasks._drain_evaluation_task(task)

    assert task.error == "boom"
    assert task.status == "error"


def test_sweep_timestamp_is_shown_without_the_iso_noise():
    """A stored sweep time renders as a readable date, not raw ISO."""
    assert evaluation_view._format_timestamp("2026-10-22T15:25:21+00:00") == "22/10/2026 15:25 UTC"
    # An unparsable value is shown unchanged instead of disappearing.
    assert evaluation_view._format_timestamp("yesterday") == "yesterday"


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

    task = tasks._EvaluationTask(total=2, status="done")
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
    assert any(
        "last_evaluation.json" in caption.value and "`" in caption.value for caption in at.caption
    )
    rendered = "\n".join(markdown.value for markdown in at.markdown)
    assert "<code>anju-kafei</code>" in rendered
    assert "<code>deed-chain</code>" in rendered
    assert "tc-cell-pass" in rendered
    assert "tc-cell-fail" in rendered
    assert "Failures by check" in rendered
    assert "tc-failure-chip" in rendered
    assert [expander.label for expander in at.expander] == [
        "`anju-kafei` — PASS",
        "`deed-chain` — FAIL",
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

    task = tasks._EvaluationTask(total=2, status="done")
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
    # Both the scenario table and the comparison table are HTML.
    assert not at.table
    rendered = "\n".join(markdown.value for markdown in at.markdown)
    assert "<code>anju-kafei</code>" in rendered
    assert "<code>deed-chain</code>" in rendered


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

    task = tasks._EvaluationTask(total=1, status="done")
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
    assert any("Run error" in error.value for error in at.error)
    assert any("LLM invocation failed" in code.value for code in at.code)


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
        return evaluation_view.EvaluationReport(results=[])

    monkeypatch.setattr(tasks, "run_scenarios", _fake_run)
    task = tasks._EvaluationTask(total=1)
    tasks._run_evaluation([scenario], rag_on=False, task=task)

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
        evaluation_view.EvaluationReport(
            results=[ScenarioResult(scenario_id="anju-kafei", passed=True)]
        )
    )

    def _failing_run(scenarios, rag_on=True, on_progress=None, should_stop=None):
        """Raise before producing any result, like an unconfigured LLM."""
        raise RuntimeError("LLM not configured")

    monkeypatch.setattr(tasks, "run_scenarios", _failing_run)
    task = tasks._EvaluationTask(total=1)
    tasks._run_evaluation([SCENARIOS_BY_ID["anju-kafei"]], rag_on=False, task=task)

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
        tasks.EvaluationReport(
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
    rendered = "\n".join(markdown.value for markdown in at.markdown)
    assert "anju-kafei" in rendered
    assert "deed-chain" in rendered
    assert [expander.label for expander in at.expander] == [
        "`anju-kafei` — PASS",
        "`deed-chain` — FAIL",
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


def test_configuration_cards_escape_values_and_gate_phoenix(monkeypatch) -> None:
    """The sidebar cards escape settings and only link Phoenix when tracing is on."""
    monkeypatch.setattr(sidebar.st, "session_state", {"lang": "en"})
    settings = Settings(
        llm_provider="<ollama>",
        llm_model="llama&3",
        rag=RAGSettings(embedding_model="sentence-transformers/model", enabled=True),
        otel_exporter_otlp_endpoint="http://localhost:6006",
    )

    markup = sidebar._configuration_html(settings)

    assert "&lt;ollama&gt;" in markup
    assert "llama&amp;3" in markup
    assert "<ollama>" not in markup
    assert 'class="tc-side-pill"' in markup
    assert "Open Phoenix" in markup
    assert 'href="http://localhost:6006"' in markup

    offline = Settings(
        llm_provider="ollama",
        llm_model="llama3.2",
        rag=RAGSettings(enabled=False),
        otel_exporter_otlp_endpoint=None,
        phoenix_base_url=None,
    )
    offline_markup = sidebar._configuration_html(offline)
    assert "tc-side-pill-off" in offline_markup
    assert "Open Phoenix" not in offline_markup
    assert ">None<" in offline_markup


def test_plan_timeline_escapes_text_and_marks_the_last_step(monkeypatch) -> None:
    """The timeline never injects plan text as HTML and flags the final step."""
    from app.domain import ClockTime, Plan, PlanStep, TimeWindow

    stub = _StreamlitStub()
    monkeypatch.setattr(plan_view, "st", stub)
    monkeypatch.setattr(formatting, "st", stub)
    monkeypatch.setattr(theme, "st", stub)
    monkeypatch.setattr(plan_view, "t", lambda key, **kwargs: key)
    monkeypatch.setattr(plan_view, "tr", lambda value: value)

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

    plan_view._render_plan(plan, valid=True)

    markup = "\n".join(value for kind, value in stub.calls if kind == "markdown")
    assert "&lt;b&gt;First&lt;/b&gt;" in markup
    assert "<b>First</b>" not in markup
    assert markup.count('class="tc-step-card"') == 2
    assert 'class="tc-step last ok"' in markup
