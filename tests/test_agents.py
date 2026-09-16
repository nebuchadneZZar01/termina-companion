"""Every agent reports which engine produced its output."""

from app.agents import critic_agent, knowledge_agent, planning_agent, state_agent
from app.data.mock_knowledge import build_default_knowledge
from app.domain import ClockTime, GameState, Goal, Plan, PlanStep, TimeWindow
from app.state import PlanningState

_KB = build_default_knowledge()


def _state(**kw) -> PlanningState:
    gs = GameState(time=ClockTime(day=2, hour=8), location="Stockpot Inn", **kw)
    return PlanningState(
        game_state=gs,
        goal=Goal(description="Reunite Anju and Kafei"),
        relevant_objectives=_KB.retrieve(gs, Goal(description="kafei letter")),
    )


def test_state_agent_is_rule_based():
    assert state_agent.run(_state())["state_engine"] == "rule-based"


def test_knowledge_agent_is_rule_based():
    assert knowledge_agent.run(_state())["knowledge_engine"] == "rule-based"


def test_critic_agent_is_rule_based():
    assert critic_agent.run(_state())["critic_engine"] == "rule-based"


def test_planning_agent_rule_based_fallback(monkeypatch):
    monkeypatch.setattr(planning_agent, "get_chat_model", lambda: None)
    result = planning_agent.run(_state())
    assert result["plan"] is not None
    assert result["plan_engine"] == "rule-based"


def test_knowledge_context_includes_objective_ids():
    from app.agents.knowledge_agent import _format

    objectives = _KB.retrieve(_state().game_state, Goal(description="kafei letter"))
    context = _format(objectives)
    assert all(f"[{o.id}]" in context for o in objectives)


def _plan_step(objective_ref, location, window):
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
    start = ClockTime(day=2, hour=9)
    window = TimeWindow(start=start, end=ClockTime(day=2, hour=10))
    plan = _plan_step("lettera", "Market District", window)
    out = planning_agent._ground_llm_steps(plan, _state().relevant_objectives)
    assert out.steps[0].objective_ref == "ak_get_letter"
    assert out.steps[0].title == "Retrieve Kafei's letter from the mailbox"


def test_ground_replaces_id_title_for_known_ref():
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
    window = TimeWindow(start=ClockTime(day=2, hour=9), end=ClockTime(day=2, hour=10))
    plan = _plan_step("mystery", "Nowhere", window)
    out = planning_agent._ground_llm_steps(plan, _state().relevant_objectives)
    assert out.steps[0].objective_ref == "mystery"
    assert out.steps[0].title == "a step"


def test_dedupe_keeps_first_occurrence_and_remaps_depends_on():
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
    def with_structured_output(self, _schema):
        return self

    def invoke(self, _msgs):
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


def test_ground_replaces_invented_location():
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
