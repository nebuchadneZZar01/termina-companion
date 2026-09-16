from app.agents.critic_agent import validate_plan
from app.domain import ClockTime, GameState, Goal, Plan, PlanStep, TimeWindow
from app.graph import MAX_PLANNING_ATTEMPTS, run_pipeline
from app.ui import _markdown_windows


def _objective(id_: str, window: TimeWindow, location: str = "Q") -> object:
    """Build a minimal Objective for tests.

    args:
        id_ (str): the objective id.
        window (TimeWindow): the objective's availability window.
        location (str, default "Q"): the objective's location.

    returns:
        object: an Objective instance.
    """
    from app.data.mock_knowledge import Objective

    return Objective(id=id_, title=id_, location=location, window=window)


def _step(title: str, window: TimeWindow, location: str = "Q", ref: str = "") -> PlanStep:
    """Build a minimal PlanStep for tests.

    args:
        title (str): the step title.
        window (TimeWindow): the step's window.
        location (str, default "Q"): the step's location.
        ref (str, default ""): the objective reference.

    returns:
        PlanStep: the created step.
    """
    return PlanStep(title=title, objective_ref=ref, location=location, window=window)


def _gs(**kw) -> GameState:
    """Build a GameState at Day 1 08:00 in location "Q".

    args:
        kw (dict): extra GameState fields.

    returns:
        GameState: the created state.
    """
    return GameState(time=ClockTime(day=1, hour=8), location="Q", **kw)


def test_empty_plan_invalid():
    """An empty plan must be invalid with an "empty" issue."""
    result = validate_plan(Plan(goal="x", steps=[]), _gs(), [])
    assert not result.valid
    assert result.issues[0].kind == "empty"


def test_timewindow_str_is_readable():
    """TimeWindow.__str__ renders a readable window, not field names."""
    w = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=2, hour=21))
    s = str(w)
    assert s == "[Day 1, 08:00 \u2192 Day 2, 21:00]"
    assert "ClockTime" not in s


def test_markdown_windows_wraps_embedded_windows():
    """_markdown_windows wraps window strings in backticks, only those."""
    msg = "falls outside the objective's slot [Day 3, 06:00 \u2192 Day 3, 12:00]."
    out = _markdown_windows(msg)
    assert "`[Day 3, 06:00 \u2192 Day 3, 12:00]`" in out
    assert _markdown_windows("no window here") == "no window here"


def test_italian_critic_message_keeps_backticks_and_window():
    """In IT, critic messages keep backticked windows untranslated (literal "Day")."""
    from unittest.mock import patch

    with patch("streamlit.session_state") as sess:
        sess.get.return_value = "it"
        from app.i18n import tr_msg

        msg = "Kafei is unavailable during [Day 3, 04:00 \u2192 Day 3, 12:00]."
        out = tr_msg(_markdown_windows(msg))
    assert "`[Day 3, 04:00 \u2192 Day 3, 12:00]`" in out
    assert "Giorno" not in out
    assert "non \u00e8 disponibile durante" in out


def test_valid_plan_passes():
    """A step inside its objective's window validates."""
    start = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    objectives = [_objective("o1", start)]
    plan = Plan(goal="x", steps=[_step("s1", start, ref="o1")])
    assert validate_plan(plan, _gs(), objectives).valid


def test_step_outside_objective_window_rejected():
    """A step scheduled outside its objective's window is a time issue."""
    slot = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    objective_window = TimeWindow(start=ClockTime(day=1, hour=10), end=ClockTime(day=1, hour=11))
    plan = Plan(goal="x", steps=[_step("s1", slot, ref="o1")])
    result = validate_plan(plan, _gs(), [_objective("o1", objective_window)])
    assert not result.valid
    assert any(i.kind == "time" for i in result.issues)


def test_missing_item_rejected():
    """A step requiring an item the player lacks is an item issue."""
    start = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    step = _step("s1", start, ref="o1")
    step.requires_items = ["Rare Item"]
    plan = Plan(goal="x", steps=[step])
    result = validate_plan(plan, _gs(), [_objective("o1", start)])
    assert not result.valid
    assert any(i.kind == "item" and "Rare Item" in i.message for i in result.issues)


def test_missing_mask_rejected():
    """A step requiring a mask the player lacks is a mask issue."""
    start = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    step = _step("s1", start, ref="o1")
    step.requires_masks = ["Goron Mask"]
    plan = Plan(goal="x", steps=[step])
    result = validate_plan(plan, _gs(), [_objective("o1", start)])
    assert not result.valid
    assert any(i.kind == "mask" and "Goron Mask" in i.message for i in result.issues)


def test_mask_available_passes():
    """A step whose required mask is owned validates."""
    start = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    step = _step("s1", start, ref="o1")
    step.requires_masks = ["Goron Mask"]
    plan = Plan(goal="x", steps=[step])
    result = validate_plan(plan, _gs(masks=["Goron Mask"]), [_objective("o1", start)])
    assert result.valid


def _npc(id_: str, **kw) -> object:
    """Build a minimal NPC for tests.

    args:
        id_ (str): the NPC id.
        kw (dict): extra NPC fields.

    returns:
        object: an NPC instance.
    """
    from app.data.mock_knowledge import NPC

    return NPC(id=id_, name=id_, location="Q", **kw)


def test_npc_unavailable_rejected():
    """A step whose NPC is out of schedule is an npc issue."""
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
    """A step whose NPC is available within the step's window validates."""
    start = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    objective = _objective("o1", start)
    objective.npc_id = "anju"
    plan = Plan(goal="x", steps=[_step("s1", start, ref="o1")])
    assert validate_plan(plan, _gs(), [objective], [_npc("anju", schedule=[start])]).valid


def test_wrong_location_rejected():
    """A step whose location differs from its objective is a location issue."""
    start = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    plan = Plan(goal="x", steps=[_step("s1", start, location="Wrong Spot", ref="o1")])
    result = validate_plan(plan, _gs(), [_objective("o1", start)])
    assert any(i.kind == "location" for i in result.issues)


def test_unsatisfied_dependency_rejected():
    """A step whose prerequisite overlaps in time is a sequence issue."""
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
    """Pipeline re-plans the naive attempt into a valid Anju & Kafei plan."""
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
    """Pipeline exhausts replans when the required item is missing."""
    gs = GameState(time=ClockTime(day=2, hour=8), location="Stockpot Inn", inventory=[])
    result = run_pipeline(
        gs, Goal(description="Reunite Anju and Kafei before the dawn of the Third Day")
    )
    assert result.validation is not None and not result.validation.valid
    assert result.replan_attempts == MAX_PLANNING_ATTEMPTS
    assert any(i.kind == "item" for i in result.validation.issues)


def test_pipeline_valid_with_required_mask():
    """Pipeline produces a valid mask-gated plan when the mask is owned."""
    gs = GameState(
        time=ClockTime(day=1, hour=8),
        location="Goron Shrine",
        masks=["Goron Mask"],
        inventory=["Lens of Truth"],
    )
    result = run_pipeline(gs, Goal(description="I want to learn the Goron Lullaby from Darmani"))
    assert result.validation is not None and result.validation.valid


def test_pipeline_gives_up_without_required_mask():
    """Pipeline exhausts replans when a required mask is missing."""
    gs = GameState(
        time=ClockTime(day=1, hour=8),
        location="Goron Shrine",
        inventory=["Lens of Truth"],
    )
    result = run_pipeline(gs, Goal(description="I want to learn the Goron Lullaby from Darmani"))
    assert result.validation is not None and not result.validation.valid
    assert result.replan_attempts == MAX_PLANNING_ATTEMPTS
    assert any(i.kind == "mask" for i in result.validation.issues)


def test_knowledge_retrieval_empty_when_no_match():
    """Search returns nothing for a goal with no matching keywords."""
    from app.mcp.tools import search_quests

    assert search_quests("completely unrelated phrase") == []


def test_knowledge_retrieval_filters_by_keywords():
    """Search returns all Anju & Kafei objectives for a kafei goal."""
    from app.mcp.tools import search_quests

    groups = search_quests("find the kafei letter")
    ids = [o["id"] for g in groups for o in g["objectives"]]
    assert len(ids) == 4  # all four Anju & Kafei objectives match
    assert all("kafei" in o["keywords"] for g in groups for o in g["objectives"])


def test_knowledge_retrieval_matches_italian_synonyms():
    """Search matches Italian synonyms in the goal description."""
    from app.mcp.tools import search_quests

    groups = search_quests("come faccio a riunire i due innamorati alla locanda")
    ids = {o["id"] for g in groups for o in g["objectives"]}
    assert ids == {"ak_talk_to_anju", "ak_reunite"}


def test_knowledge_npc_schedules_and_events():
    """The knowledge base exposes NPC schedules, events and locations."""
    from app.data.mock_knowledge import build_default_knowledge

    kb = build_default_knowledge()
    assert kb.npc("anju").available_at(ClockTime(day=2, hour=9))
    assert not kb.npc("anju").available_at(ClockTime(day=1, hour=23))
    assert kb.event("ak_letter_delivery").name == "Kafei's letter is delivered"
    assert len(kb.locations) >= 6
    ak_deliver = next(o for q in kb.quests for o in q.objectives if o.id == "ak_deliver_letter")
    assert ak_deliver.npc_id == "kafei"
