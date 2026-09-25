"""Every agent reports which engine produced its output."""

import pytest

from app.agents import critic_agent, knowledge_agent, planning_agent, state_agent
from app.agents.planning_agent import PlanningAgentError
from app.data.mock_knowledge import Objective, build_default_knowledge
from app.domain import ClockTime, GameState, Goal, Plan, PlanStep, TimeWindow
from app.mcp.tools import search_quests
from app.state import PlanningState

_KB = build_default_knowledge()


def _relevant(description: str) -> list[Objective]:
    """Objectives matched by the MCP search tool for a goal text."""
    groups = search_quests(description)
    return [Objective.model_validate(obj) for group in groups for obj in group["objectives"]]


def _state(**kw) -> PlanningState:
    """Build a PlanningState on the Anju & Kafei quest for tests.

    args:
        kw (dict): extra GameState fields.

    returns:
        PlanningState: a state at Day 2 08:00 in the Stockpot Inn.
    """
    gs = GameState(time=ClockTime(day=2, hour=8), location="Stockpot Inn", **kw)
    return PlanningState(
        game_state=gs,
        goal=Goal(description="Reunite Anju and Kafei"),
        relevant_objectives=_relevant("kafei letter"),
    )


def test_state_agent_is_rule_based():
    """The State Agent reports the rule-based engine."""
    assert state_agent.run(_state())["state_engine"] == "rule-based"


def test_state_agent_summary_includes_active_quest():
    """At the Stockpot Inn the summary names the Anju & Kafei quest."""
    summary = state_agent.run(_state())["state_summary"]
    assert "Active: Anju and Kafei" in summary
    assert "Talk to Anju at the Stockpot Inn" in summary


def test_progress_summary_lists_completed_quest():
    """A quest marked done in quest_progress is reported as completed."""
    from app.agents.state_agent import _progress_summary

    kb = build_default_knowledge()
    out = _progress_summary({"anju_kafei": "done"}, kb, "Stockpot Inn")
    assert "Completed quests: Anju and Kafei" in out


def test_progress_summary_empty_away_from_objectives():
    """No progress is reported when the location has no objectives."""
    from app.agents.state_agent import _progress_summary

    kb = build_default_knowledge()
    assert _progress_summary({}, kb, "Snowhead") == ""


def test_knowledge_agent_is_rule_based():
    """The Knowledge Agent reports the rule-based engine."""
    assert knowledge_agent.run(_state())["knowledge_engine"] == "rule-based"


def test_critic_agent_is_rule_based():
    """The Critic Agent reports the rule-based engine."""
    assert critic_agent.run(_state())["critic_engine"] == "rule-based"


def test_planning_agent_requires_llm(monkeypatch):
    """The Planning Agent fails explicitly when no LLM is available."""
    monkeypatch.setattr(planning_agent, "get_chat_model", lambda **kw: None)
    with pytest.raises(PlanningAgentError, match="requires a configured LLM"):
        planning_agent.run(_state())


def test_planning_agent_threads_llm_config(monkeypatch):
    """The LLM config set on the state is forwarded to get_chat_model."""
    captured: dict = {}

    def _spy(**kw):
        captured.update(kw)
        return _FakeModel()

    monkeypatch.setattr(planning_agent, "get_chat_model", _spy)
    state = _state().model_copy(
        update={"llm_config": {"provider": "openai", "model": "gpt-x", "api_key": "k"}}
    )
    planning_agent.run(state)
    assert captured == {"provider": "openai", "model": "gpt-x", "api_key": "k"}


def test_knowledge_context_includes_objective_ids():
    """The knowledge context lists each retrieved objective by its id."""
    from app.agents.knowledge_agent import _format
    from app.mcp.tools import get_event, get_npc_schedule

    objectives = _relevant("kafei letter")
    npc_schedules = {o.npc_id: get_npc_schedule(o.npc_id) for o in objectives if o.npc_id}
    events = {o.event_ref: get_event(o.event_ref) for o in objectives if o.event_ref}
    context = _format(objectives, npc_schedules, events)
    assert all(f"[{o.id}]" in context for o in objectives)


def _plan_step(objective_ref, location, window):
    """Build a one-step Plan for tests.

    args:
        objective_ref (str): the step's objective reference.
        location (str): the step's location.
        window (TimeWindow): the step's window.

    returns:
        Plan: a Plan with a single step.
    """
    return Plan(
        goal="x",
        steps=[
            PlanStep(
                title="a step",
                objective_ref=objective_ref,
                location=location,
                window=window,
            )
        ],
    )


def test_ground_repairs_location_and_window_match():
    """Grounding fixes the ref and title for an alias objective."""
    start = ClockTime(day=2, hour=9)
    window = TimeWindow(start=start, end=ClockTime(day=2, hour=10))
    plan = _plan_step("lettera", "Market District", window)
    out = planning_agent._ground_llm_steps(plan, _state().relevant_objectives)
    assert out.steps[0].objective_ref == "ak_get_letter"
    assert out.steps[0].title == "Retrieve Kafei's letter from the mailbox"


def test_ground_replaces_id_title_for_known_ref():
    """Grounding replaces a bare [id] title with the objective's title."""
    start = ClockTime(day=2, hour=9)
    window = TimeWindow(start=start, end=ClockTime(day=2, hour=10))
    plan = Plan(
        goal="x",
        steps=[
            PlanStep(
                title="[ak_get_letter]",
                objective_ref="ak_get_letter",
                location="Market District",
                window=window,
            )
        ],
    )
    out = planning_agent._ground_llm_steps(plan, _state().relevant_objectives)
    assert out.steps[0].title == "Retrieve Kafei's letter from the mailbox"


def test_ground_leaves_unknown_untouched():
    """Grounding leaves unknown objective refs untouched."""
    window = TimeWindow(start=ClockTime(day=2, hour=9), end=ClockTime(day=2, hour=10))
    plan = _plan_step("mystery", "Nowhere", window)
    out = planning_agent._ground_llm_steps(plan, _state().relevant_objectives)
    assert out.steps[0].objective_ref == "mystery"
    assert out.steps[0].title == "a step"


def test_dedupe_keeps_first_occurrence_and_remaps_depends_on():
    """Deduplication drops repeated refs and remaps dependencies."""
    w = TimeWindow(start=ClockTime(day=2, hour=9), end=ClockTime(day=2, hour=10))
    plan = Plan(
        goal="x",
        steps=[
            PlanStep(
                title="s1",
                objective_ref="ak_get_letter",
                location="Market District",
                window=w,
            ),
            PlanStep(
                title="s2",
                objective_ref="ak_talk_to_anju",
                location="Stockpot Inn",
                window=w,
                depends_on=[0],
            ),
            PlanStep(
                title="s3 dup",
                objective_ref="ak_talk_to_anju",
                location="Stockpot Inn",
                window=w,
                depends_on=[1],
            ),
            PlanStep(title="s4 no ref", location="Q", window=w, depends_on=[2]),
        ],
    )
    out = planning_agent._dedupe_steps(plan)
    assert [s.objective_ref for s in out.steps] == ["ak_get_letter", "ak_talk_to_anju", ""]
    assert out.steps[1].depends_on == [0]
    assert out.steps[2].depends_on == []  # dep pointed at the dropped duplicate


class _FakeModel:
    _invoked: list = []
    model_name = "fake-model"

    def with_structured_output(self, _schema):
        """Pretend to bind a structured-output schema and return self."""
        return self

    def invoke(self, msgs):
        """Capture the prompt and return a canned grounded Plan."""
        _FakeModel._invoked = msgs
        start = ClockTime(day=2, hour=9)
        window = TimeWindow(start=start, end=ClockTime(day=2, hour=10))
        return Plan(
            goal="x",
            steps=[
                PlanStep(
                    title="[ak_get_letter]",
                    objective_ref="ak_get_letter",
                    location="market_district",
                    window=window,
                ),
                PlanStep(
                    title="a step",
                    objective_ref="ak_talk_to_anju",
                    location="Stockpot Inn",
                    window=window,
                    depends_on=[0],
                ),
                PlanStep(
                    title="duplicate",
                    objective_ref="ak_talk_to_anju",
                    location="Stockpot Inn",
                    window=window,
                    depends_on=[1],
                ),
            ],
        )


class _EmptyModel:
    model_name = "empty-model"

    def with_structured_output(self, _schema):
        return self

    def invoke(self, _msgs):
        return Plan(goal="x", steps=[])


def test_planning_agent_rejects_empty_llm_plan(monkeypatch):
    """An empty LLM response is an explicit planning failure."""
    monkeypatch.setattr(planning_agent, "get_chat_model", lambda **kw: _EmptyModel())
    with pytest.raises(PlanningAgentError, match="empty plan"):
        planning_agent.run(_state())


def test_planning_agent_skips_owned_provide_step(monkeypatch):
    """ "Retrieve the letter" is pruned once the player already owns it."""
    monkeypatch.setattr(planning_agent, "get_chat_model", lambda **kw: _FakeModel())
    result = planning_agent.run(_state(inventory=["Kafei's Letter"]))
    refs = [s.objective_ref for s in result["plan"].steps]
    assert refs == ["ak_talk_to_anju", "ak_deliver_letter", "ak_reunite"]
    assert result["plan"].steps[1].depends_on == []  # its prerequisite was pruned


def test_reconcile_orders_and_completes_chain():
    """Reconciling inserts chain steps the generator skipped, in prerequisite order."""
    window = TimeWindow(start=ClockTime(day=3, hour=6), end=ClockTime(day=3, hour=7))
    plan = Plan(
        goal="x", steps=[_plan_step("ak_deliver_letter", "Curiosity Shop", window).steps[0]]
    )
    out = planning_agent._reconcile_plan(plan, _state())
    refs = [s.objective_ref for s in out.steps]
    assert refs == [
        "ak_talk_to_anju",
        "ak_get_letter",
        "ak_deliver_letter",
        "ak_reunite",
    ]
    assert [s.depends_on for s in out.steps] == [[], [0], [1], [2]]


def test_planning_agent_llm_plan_is_grounded(monkeypatch):
    """An LLM-produced plan is grounded and completed to the full chain."""
    monkeypatch.setattr(planning_agent, "get_chat_model", lambda **kw: _FakeModel())
    result = planning_agent.run(_state())
    assert result["plan_engine"] == "llm"
    assert result["plan_model"] == "fake-model"
    refs = [s.objective_ref for s in result["plan"].steps]
    assert refs == ["ak_talk_to_anju", "ak_get_letter", "ak_deliver_letter", "ak_reunite"]
    step = result["plan"].steps[1]
    assert step.title == "Retrieve Kafei's letter from the mailbox"
    assert step.location == "Market District"
    assert step.requires_items == []  # ak_get_letter needs nothing from the player
    assert step.depends_on == [0]


def test_planning_prompt_enforces_window_containment(monkeypatch):
    """The LLM prompt binds each step's window inside the objective's window."""
    monkeypatch.setattr(planning_agent, "get_chat_model", lambda **kw: _FakeModel())
    planning_agent.run(_state())
    system = next(m.content for m in _FakeModel._invoked if m.type == "system")
    assert "objective's bracketed window" in system
    assert "step.window.start >= that window's start" in system
    assert "step.window.end <= that window's end" in system


def test_clamp_windows_pins_window_inside_objective_slot():
    """A window spanning outside the slot is cut to the intersection."""
    w = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=2, hour=21))
    plan = _plan_step("ak_talk_to_anju", "Stockpot Inn", w)
    out = planning_agent._clamp_windows(plan, _state().relevant_objectives)
    assert out.steps[0].objective_ref == "ak_talk_to_anju"
    assert out.steps[0].window.start == ClockTime(day=2, hour=8)
    assert out.steps[0].window.end == ClockTime(day=2, hour=21)


def test_clamp_windows_falls_back_when_window_is_disjoint():
    """A window fully outside the slot falls back inside the objective's."""
    w = TimeWindow(start=ClockTime(day=3, hour=10), end=ClockTime(day=3, hour=11))
    plan = _plan_step("ak_get_letter", "Market District", w)
    state = _state()
    out = planning_agent._clamp_windows(plan, state.relevant_objectives)
    obj = next(o for o in state.relevant_objectives if o.id == "ak_get_letter")
    step_window = out.steps[0].window
    assert step_window.start == obj.window.start
    start = (step_window.start.day, step_window.start.hour, step_window.start.minute)
    end = (step_window.end.day, step_window.end.hour, step_window.end.minute)
    obj_end = (obj.window.end.day, obj.window.end.hour, obj.window.end.minute)
    assert start < end <= obj_end


def test_clamp_windows_leaves_ungrounded_steps_untouched():
    """Steps with an unknown objective ref pass through unchanged."""
    w = TimeWindow(start=ClockTime(day=3, hour=10), end=ClockTime(day=3, hour=11))
    plan = _plan_step("mystery", "Nowhere", w)
    out = planning_agent._clamp_windows(plan, _state().relevant_objectives)
    assert out.steps[0].window == w


def test_ground_replaces_invented_location():
    """Grounding replaces an invented location and fills requirements."""
    window = TimeWindow(start=ClockTime(day=3, hour=6), end=ClockTime(day=3, hour=7))
    plan = Plan(
        goal="x",
        steps=[
            PlanStep(
                title="[ak_deliver_letter]",
                objective_ref="ak_deliver_letter",
                location="curiosity_shop",
                window=window,
            )
        ],
    )
    out = planning_agent._ground_llm_steps(plan, _state().relevant_objectives)
    assert out.steps[0].location == "Curiosity Shop"
    assert out.steps[0].requires_items == ["Kafei's Letter"]


def test_reconcile_re_slots_kept_steps_after_dependencies():
    """On replan, LLM slot-width windows are re-slotted into 1h, dep-ordered."""
    state = _state().model_copy(update={"replan_attempts": 1})
    plan = Plan(
        goal="x",
        steps=[
            _plan_step(
                "ak_talk_to_anju",
                "Stockpot Inn",
                TimeWindow(start=ClockTime(day=2, hour=8), end=ClockTime(day=2, hour=21)),
            ).steps[0],
            _plan_step(
                "ak_get_letter",
                "Market District",
                TimeWindow(start=ClockTime(day=2, hour=9), end=ClockTime(day=2, hour=17)),
            ).steps[0],
            _plan_step(
                "ak_deliver_letter",
                "Curiosity Shop",
                TimeWindow(start=ClockTime(day=3, hour=6), end=ClockTime(day=3, hour=12)),
            ).steps[0],
            _plan_step(
                "ak_reunite",
                "Stockpot Inn",
                TimeWindow(start=ClockTime(day=3, hour=22), end=ClockTime(day=3, hour=23)),
            ).steps[0],
        ],
    )
    out = planning_agent._reconcile_plan(plan, state)
    assert [s.depends_on for s in out.steps] == [[], [0], [1], [2]]
    assert out.steps[0].window == TimeWindow(
        start=ClockTime(day=2, hour=8), end=ClockTime(day=2, hour=9)
    )
    assert out.steps[1].window == TimeWindow(
        start=ClockTime(day=2, hour=9), end=ClockTime(day=2, hour=10)
    )
    assert out.steps[2].window.start == ClockTime(day=3, hour=6)
    start = out.steps[3].window.start
    end = out.steps[2].window.end
    assert (start.day, start.hour, start.minute) >= (end.day, end.hour, end.minute)


def test_to_step_carries_requires_masks():
    """_to_step carries an objective's required masks into the step."""
    obj = next(o for q in _KB.quests for o in q.objectives if o.id == "dg_talk_elder")
    step = planning_agent._to_step(
        obj, TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9)), []
    )
    assert step.requires_masks == ["Goron Mask"]


def test_knowledge_covers_all_major_areas():
    """Knowledge locations cover all six major game areas."""
    areas = {loc.area for loc in _KB.locations}
    assert {
        "Clock Town",
        "Southern Swamp",
        "Mountain Village",
        "Great Bay",
        "Ikana Canyon",
        "Romani Ranch",
    } <= areas


def test_i18n_covers_all_knowledge_strings():
    """Every objective title, description and location has an IT translation."""
    from app.i18n import _DISPLAY_IT

    missing = [
        f"{q.id}: {text!r}"
        for q in _KB.quests
        for o in q.objectives
        for text in (o.title, o.description, o.location)
        if text and text not in _DISPLAY_IT
    ]
    assert not missing, "Missing IT translations:\n" + "\n".join(missing)
