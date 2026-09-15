from app.agents.critic_agent import validate_plan
from app.domain import ClockTime, GameState, Goal, Plan, PlanStep, TimeWindow
from app.graph import MAX_PLANNING_ATTEMPTS, run_pipeline


def _objective(id_: str, window: TimeWindow, location: str = "Q") -> object:
    from app.data.mock_knowledge import Objective

    return Objective(id=id_, title=id_, location=location, window=window)


def _step(title: str, window: TimeWindow, location: str = "Q", ref: str = "") -> PlanStep:
    return PlanStep(title=title, objective_ref=ref, location=location, window=window)


def _gs(**kw) -> GameState:
    return GameState(time=ClockTime(day=1, hour=8), location="Q", **kw)


def test_empty_plan_invalid():
    result = validate_plan(Plan(goal="x", steps=[]), _gs(), [])
    assert not result.valid
    assert result.issues[0].kind == "empty"


def test_valid_plan_passes():
    start = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    objectives = [_objective("o1", start)]
    plan = Plan(goal="x", steps=[_step("s1", start, ref="o1")])
    assert validate_plan(plan, _gs(), objectives).valid


def test_step_outside_objective_window_rejected():
    slot = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    objective_window = TimeWindow(start=ClockTime(day=1, hour=10), end=ClockTime(day=1, hour=11))
    plan = Plan(goal="x", steps=[_step("s1", slot, ref="o1")])
    result = validate_plan(plan, _gs(), [_objective("o1", objective_window)])
    assert not result.valid
    assert any(i.kind == "time" for i in result.issues)


def test_missing_item_rejected():
    start = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    step = _step("s1", start, ref="o1")
    step.requires_items = ["Rare Item"]
    plan = Plan(goal="x", steps=[step])
    result = validate_plan(plan, _gs(), [_objective("o1", start)])
    assert not result.valid
    assert any(i.kind == "item" and "Rare Item" in i.message for i in result.issues)


def _npc(id_: str, **kw) -> object:
    from app.data.mock_knowledge import NPC

    return NPC(id=id_, name=id_, location="Q", **kw)


def test_npc_unavailable_rejected():
    from app.data.mock_knowledge import NPC

    start = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    objective = _objective("o1", start)
    objective.npc_id = "bartender"
    plan = Plan(goal="x", steps=[_step("s1", start, ref="o1")])
    npcs = [
        NPC(
            id="bartender",
            name="Bartender",
            location="Q",
            schedule=[TimeWindow(start=ClockTime(day=1, hour=10), end=ClockTime(day=1, hour=11))],
        )
    ]
    result = validate_plan(plan, _gs(), [objective], npcs)
    assert not result.valid
    assert any(i.kind == "npc" and "bartender" in i.message.lower() for i in result.issues)


def test_npc_available_passes():
    start = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    objective = _objective("o1", start)
    objective.npc_id = "anju"
    plan = Plan(goal="x", steps=[_step("s1", start, ref="o1")])
    assert validate_plan(plan, _gs(), [objective], [_npc("anju", schedule=[start])]).valid


def test_wrong_location_rejected():
    start = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    plan = Plan(goal="x", steps=[_step("s1", start, location="Wrong Spot", ref="o1")])
    result = validate_plan(plan, _gs(), [_objective("o1", start)])
    assert any(i.kind == "location" for i in result.issues)


def test_unsatisfied_dependency_rejected():
    early = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    later_window = TimeWindow(
        start=ClockTime(day=1, hour=8, minute=30), end=ClockTime(day=1, hour=9, minute=30)
    )
    late = _step("s2", later_window, ref="o2")
    late.depends_on = [0]
    plan = Plan(goal="x", steps=[_step("s1", early, ref="o1"), late])
    objectives = [_objective("o1", early), _objective("o2", later_window)]
    assert any(i.kind == "sequence" for i in validate_plan(plan, _gs(), objectives).issues)


def test_pipeline_replans_to_feasible_plan_with_letter():
    gs = GameState(
        time=ClockTime(day=2, hour=8),
        location="Stockpot Inn",
        inventory=["Kafei's Letter"],
    )
    result = run_pipeline(
        gs, Goal(description="Reunite Anju and Kafei before the dawn of the Third Day")
    )
    assert result.validation is not None and result.validation.valid
    assert result.replan_attempts == 2  # naive attempt invalid -> re-plan under objective windows


def test_pipeline_gives_up_without_required_item():
    gs = GameState(time=ClockTime(day=2, hour=8), location="Stockpot Inn", inventory=[])
    result = run_pipeline(
        gs, Goal(description="Reunite Anju and Kafei before the dawn of the Third Day")
    )
    assert result.validation is not None and not result.validation.valid
    assert result.replan_attempts == MAX_PLANNING_ATTEMPTS
    assert any(i.kind == "item" for i in result.validation.issues)


def test_knowledge_retrieval_filters_by_keywords():
    from app.data.mock_knowledge import build_default_knowledge

    kb = build_default_knowledge()
    gs = _gs()
    anju = kb.retrieve(gs, Goal(description="find the kafei letter"))
    assert all("kafei" in o.keywords for o in anju)
    assert len({o.id for o in anju}) == 4  # all four Anju & Kafei objectives match


def test_knowledge_npc_schedules_and_events():
    from app.data.mock_knowledge import build_default_knowledge

    kb = build_default_knowledge()
    assert kb.npc("anju").available_at(ClockTime(day=2, hour=9))
    assert not kb.npc("anju").available_at(ClockTime(day=1, hour=23))
    assert kb.event("ak_letter_delivery").name == "Kafei's letter is delivered"
    assert len(kb.locations) >= 6
    ak_deliver = next(o for q in kb.quests for o in q.objectives if o.id == "ak_deliver_letter")
    assert ak_deliver.npc_id == "kafei"
