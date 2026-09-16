"""Every agent reports which engine produced its output."""

from app.agents import critic_agent, knowledge_agent, planning_agent, state_agent
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


def test_knowledge_agent_is_rule_based():
    """The Knowledge Agent reports the rule-based engine."""
    assert knowledge_agent.run(_state())["knowledge_engine"] == "rule-based"


def test_critic_agent_is_rule_based():
    """The Critic Agent reports the rule-based engine."""
    assert critic_agent.run(_state())["critic_engine"] == "rule-based"


def test_planning_agent_rule_based_fallback(monkeypatch):
    """The Planning Agent falls back to rule-based without an LLM."""
    monkeypatch.setattr(planning_agent, "get_chat_model", lambda: None)
    result = planning_agent.run(_state())
    assert result["plan"] is not None
    assert result["plan_engine"] == "rule-based"


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


def test_planning_agent_llm_plan_is_grounded(monkeypatch):
    """An LLM-produced plan is grounded: refs, titles, locations, deps."""
    monkeypatch.setattr(planning_agent, "get_chat_model", lambda: _FakeModel())
    result = planning_agent.run(_state())
    assert result["plan_engine"] == "llm"
    step = result["plan"].steps[0]
    assert step.objective_ref == "ak_get_letter"
    assert step.title == "Retrieve Kafei's letter from the mailbox"
    assert step.location == "Market District"
    assert step.requires_items == []  # ak_get_letter needs nothing from the player
    refs = [s.objective_ref for s in result["plan"].steps]
    assert refs == ["ak_get_letter", "ak_talk_to_anju"]
    assert result["plan"].steps[1].depends_on == [0]


def test_planning_prompt_enforces_window_containment(monkeypatch):
    """The LLM prompt binds each step's window inside the objective's window."""
    monkeypatch.setattr(planning_agent, "get_chat_model", lambda: _FakeModel())
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


def test_to_step_carries_requires_masks():
    """_to_step carries an objective's required masks into the step."""
    obj = next(o for q in _KB.quests for o in q.objectives if o.id == "dg_talk_elder")
    step = planning_agent._to_step(
        obj, 0, TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
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
