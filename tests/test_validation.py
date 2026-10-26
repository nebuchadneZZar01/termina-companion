import pytest

from app.agents import critic_agent
from app.agents.critic_agent import validate_plan
from app.domain import (
    ClockTime,
    GameState,
    Goal,
    Plan,
    PlanStep,
    TimeWindow,
    ValidationIssue,
    ValidationResult,
)
from app.graph import run_pipeline
from app.ui.formatting import _markdown_windows

pytestmark = pytest.mark.usefixtures("fake_planner_model")


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


def test_italian_quest_prerequisite_message_translates_the_tail():
    """The stale template used to leave the final sentence in English."""
    from unittest.mock import patch

    with patch("streamlit.session_state") as sess:
        sess.get.return_value = "it"
        from app.i18n import tr_msg

        out = tr_msg("Quest prerequisite missing: Anju. Complete this quest first.")
    assert out == "Prerequisito quest mancante: Anju. Completa questa quest prima."


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
    """A required item missing from the Objective is an item issue."""
    start = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    objective = _objective("o1", start)
    objective.requires_items = ["Rare Item"]
    plan = Plan(goal="x", steps=[_step("s1", start, ref="o1")])
    result = validate_plan(plan, _gs(), [objective])
    assert not result.valid
    assert any(i.kind == "item" and "Rare Item" in i.message for i in result.issues)


def test_missing_mask_rejected():
    """A required mask missing from the Objective is a mask issue."""
    start = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    objective = _objective("o1", start)
    objective.requires_masks = ["Goron Mask"]
    plan = Plan(goal="x", steps=[_step("s1", start, ref="o1")])
    result = validate_plan(plan, _gs(), [objective])
    assert not result.valid
    assert any(i.kind == "mask" and "Goron Mask" in i.message for i in result.issues)


def test_mask_available_passes():
    """A step whose authoritative required mask is owned validates."""
    start = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    objective = _objective("o1", start)
    objective.requires_masks = ["Goron Mask"]
    plan = Plan(goal="x", steps=[_step("s1", start, ref="o1")])
    result = validate_plan(plan, _gs(masks=["Goron Mask"]), [objective])
    assert result.valid


def test_step_fields_cannot_hide_an_objective_requirement():
    """A grounded step that dropped its requirement is still rejected."""
    start = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    objective = _objective("o1", start)
    objective.requires_items = ["Rare Item"]
    step = _step("s1", start, ref="o1")
    assert step.requires_items == []
    result = validate_plan(Plan(goal="x", steps=[step]), _gs(), [objective])
    assert any(i.kind == "item" and "Rare Item" in i.message for i in result.issues)


def test_extra_step_requirement_is_not_checked():
    """A requirement only present on the step is not a feasibility failure."""
    start = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    step = _step("s1", start, ref="o1")
    step.requires_masks = ["Invented Mask"]
    result = validate_plan(Plan(goal="x", steps=[step]), _gs(), [_objective("o1", start)])
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
    """Dependency timing is recomputed from the objective's prerequisites."""
    early = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    later_window = TimeWindow(
        start=ClockTime(day=1, hour=8, minute=30), end=ClockTime(day=1, hour=9, minute=30)
    )
    o2 = _objective("o2", later_window)
    o2.prerequisites = ["o1"]
    late = _step("s2", later_window, ref="o2")
    assert late.depends_on == []
    plan = Plan(goal="x", steps=[_step("s1", early, ref="o1"), late])
    objectives = [_objective("o1", early), o2]
    result = validate_plan(plan, _gs(), objectives)
    assert any(i.kind == "sequence" for i in result.issues)


def test_overlapping_consecutive_steps_rejected():
    """Independent consecutive steps that overlap are flagged globally."""
    early = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    later_window = TimeWindow(
        start=ClockTime(day=1, hour=8, minute=30), end=ClockTime(day=1, hour=9, minute=30)
    )
    plan = Plan(
        goal="x",
        steps=[_step("s1", early, ref="o1"), _step("s2", later_window, ref="o2")],
    )
    result = validate_plan(plan, _gs(), [_objective("o1", early), _objective("o2", later_window)])
    assert not result.valid
    assert any(i.kind == "overlap" for i in result.issues)


def test_sequential_consecutive_steps_pass():
    """Steps that merely touch at the boundary do not overlap."""
    early = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    later_window = TimeWindow(start=ClockTime(day=1, hour=9), end=ClockTime(day=1, hour=10))
    plan = Plan(
        goal="x",
        steps=[_step("s1", early, ref="o1"), _step("s2", later_window, ref="o2")],
    )
    assert validate_plan(
        plan, _gs(), [_objective("o1", early), _objective("o2", later_window)]
    ).valid


def test_unknown_objective_ref_rejected():
    """An unknown reference is an error, never a skipped check."""
    start = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    plan = Plan(goal="x", steps=[_step("s1", start, ref="not_a_real_objective")])
    result = validate_plan(plan, _gs(), [_objective("o1", start)])
    assert not result.valid
    assert [i.kind for i in result.issues] == ["objective"]
    assert "not_a_real_objective" in result.issues[0].message


def test_empty_objective_ref_rejected():
    """A step without a reference cannot be verified and is rejected."""
    start = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    plan = Plan(goal="x", steps=[_step("s1", start, ref="")])
    result = validate_plan(plan, _gs(), [_objective("o1", start)])
    assert [i.kind for i in result.issues] == ["objective"]


def test_ref_outside_relevant_objectives_resolves_against_the_kb():
    """A ref known to the knowledge base validates even when not retrieved."""
    from app.data.mock_knowledge import build_default_knowledge

    kb = build_default_knowledge()
    objective = next(o for q in kb.quests for o in q.objectives if o.id == "ak_get_kafei_mask")
    step = _step("mask", objective.window, location=objective.location, ref=objective.id)
    result = validate_plan(Plan(goal="x", steps=[step]), _gs(), [])
    assert result.valid


def test_pipeline_builds_feasible_plan_with_required_gear():
    """The LLM plan is reconciled into a valid Anju & Kafei plan."""
    gs = GameState(
        time=ClockTime(day=1, hour=6),
        location="South Clock Town",
        inventory=["Hookshot"],
        masks=["Garo's Mask"],
    )
    result = run_pipeline(
        gs, Goal(description="Reunite Anju and Kafei before the dawn of the Third Day")
    )
    assert result.validation is not None and result.validation.valid
    assert result.replan_attempts == 1


def test_pipeline_replans_after_critic_failure(monkeypatch):
    """A Critic failure sends the graph back to the LLM planner."""
    critic_calls = 0
    real_critic = critic_agent.run

    def _critic_with_one_forced_failure(state):
        nonlocal critic_calls
        critic_calls += 1
        if critic_calls == 1:
            return {
                "validation": ValidationResult(
                    valid=False,
                    issues=[
                        ValidationIssue(
                            severity="error",
                            kind="forced",
                            message="Forced test failure.",
                        )
                    ],
                ),
                "critic_engine": "rule-based",
            }
        return real_critic(state)

    monkeypatch.setattr(critic_agent, "run", _critic_with_one_forced_failure)
    result = run_pipeline(
        GameState(
            time=ClockTime(day=1, hour=6),
            location="South Clock Town",
            inventory=["Hookshot"],
            masks=["Garo's Mask"],
        ),
        Goal(description="Reunite Anju and Kafei before the dawn of the Third Day"),
    )

    assert result.validation is not None and result.validation.valid
    assert result.replan_attempts == 2
    assert critic_calls == 2


def test_pipeline_valid_when_item_is_provided_by_plan():
    """A required item is credited when an earlier step provides it."""
    gs = GameState(
        time=ClockTime(day=1, hour=6),
        location="South Clock Town",
        inventory=["Hookshot"],
        masks=["Garo's Mask"],
    )
    result = run_pipeline(
        gs, Goal(description="Reunite Anju and Kafei before the dawn of the Third Day")
    )
    assert result.validation is not None and result.validation.valid
    refs = [s.objective_ref for s in result.plan.steps]
    assert refs == [
        "ak_get_kafei_mask",
        "ak_get_room_key",
        "ak_talk_to_anju",
        "ak_meet_in_kitchen",
        "ak_post_letter",
        "ak_meet_kafei",
        "ak_deliver_pendant",
        "ak_sakon_hideout",
        "ak_reunite",
    ]


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


def test_pipeline_valid_when_mask_is_acquired_in_plan():
    """Pipeline acquires a missing mask before the steps that need it."""
    gs = GameState(
        time=ClockTime(day=1, hour=8),
        location="Goron Shrine",
        inventory=["Lens of Truth"],
    )
    result = run_pipeline(gs, Goal(description="I want to learn the Goron Lullaby from Darmani"))
    assert result.validation is not None and result.validation.valid
    refs = [s.objective_ref for s in result.plan.steps]
    assert "dg_heal_darmani" in refs
    assert refs.index("dg_heal_darmani") < refs.index("dg_get_hot_spring")


def test_pipeline_valid_when_item_is_acquired_in_plan():
    """Pipeline acquires a missing item before the steps that need it."""
    gs = GameState(
        time=ClockTime(day=1, hour=6),
        location="North Clock Town",
    )
    result = run_pipeline(gs, Goal(description="I want the Bomber's Notebook from the gang"))
    assert result.validation is not None and result.validation.valid
    refs = [s.objective_ref for s in result.plan.steps]
    assert refs == ["bm_pop_balloon", "bm_hide_and_seek", "bm_get_notebook", "bm_enter_hideout"]


def test_pipeline_gates_a_quest_behind_missing_prerequisites():
    """A quest with unmet prerequisites stops at the gate, planning only itself."""
    gs = GameState(
        time=ClockTime(day=1, hour=9),
        location="Ikana Canyon",
    )
    result = run_pipeline(gs, Goal(description="Free Pamela's father in the Music Box House"))

    assert result.validation is not None and not result.validation.valid
    assert {issue.kind for issue in result.validation.issues} == {"quest_prerequisite"}
    message = " ".join(issue.message for issue in result.validation.issues)
    assert "Song of Storms" in message
    assert "Deku Princess Rescue" in message
    refs = [s.objective_ref for s in result.plan.steps]
    assert refs
    assert all(ref.startswith("pf_") for ref in refs)


def test_knowledge_retrieval_empty_when_no_match():
    """Search returns nothing for a goal with no matching keywords."""
    from app.mcp.tools import search_quests

    assert search_quests("completely unrelated phrase") == []


def test_knowledge_retrieval_filters_by_keywords():
    """Search returns all Anju & Kafei objectives for a kafei goal."""
    from app.mcp.tools import search_quests

    groups = search_quests("find the kafei letter")
    ids = [o["id"] for g in groups for o in g["objectives"]]
    assert len(ids) == 9  # the whole Anju & Kafei chain comes back
    assert all("kafei" in o["keywords"] for g in groups for o in g["objectives"])


def test_knowledge_retrieval_matches_italian_synonyms():
    """Search matches Italian synonyms and returns the full quest chain."""
    from app.mcp.tools import search_quests

    groups = search_quests("come faccio a riunire i due innamorati alla locanda")
    ids = {o["id"] for g in groups for o in g["objectives"]}
    assert ids == {
        "ak_get_kafei_mask",
        "ak_get_room_key",
        "ak_talk_to_anju",
        "ak_meet_in_kitchen",
        "ak_post_letter",
        "ak_meet_kafei",
        "ak_deliver_pendant",
        "ak_sakon_hideout",
        "ak_reunite",
    }


def test_knowledge_retrieval_returns_full_quest():
    """A single objective match pulls in the whole quest, prerequisites first."""
    from app.mcp.tools import search_quests

    groups = search_quests("parla alla locanda")  # matches only ak_talk_to_anju
    ids = [o["id"] for g in groups for o in g["objectives"]]
    assert ids == [
        "ak_get_kafei_mask",
        "ak_get_room_key",
        "ak_talk_to_anju",
        "ak_meet_in_kitchen",
        "ak_post_letter",
        "ak_meet_kafei",
        "ak_deliver_pendant",
        "ak_sakon_hideout",
        "ak_reunite",
    ]


def test_missing_prerequisite_rejected():
    """A step whose prerequisite objective is absent is a prerequisite issue."""
    start = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    o1 = _objective("o1", start)
    o2 = _objective("o2", start)
    o2.prerequisites = ["o1"]
    plan = Plan(goal="x", steps=[_step("s2", start, ref="o2")])
    result = validate_plan(plan, _gs(), [o1, o2])
    assert not result.valid
    assert any(i.kind == "prerequisite" and "o1" in i.message for i in result.issues)


def test_prerequisite_satisfied_by_owned_provide_passes():
    """A prerequisite is satisfied when its provide is already owned."""
    start = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    o1 = _objective("o1", start)
    o1.provides_items = ["Secret Letter"]
    o2 = _objective("o2", start)
    o2.prerequisites = ["o1"]
    plan = Plan(goal="x", steps=[_step("s2", start, ref="o2")])
    result = validate_plan(plan, _gs(inventory=["Secret Letter"]), [o1, o2])
    assert result.valid


def test_prerequisite_satisfied_by_done_quest_passes():
    """A prerequisite in a completed quest counts as satisfied."""
    from app.data.mock_knowledge import build_default_knowledge

    kb = build_default_knowledge()
    deliver = next(o for q in kb.quests for o in q.objectives if o.id == "ak_deliver_pendant")
    step = _step("deliver", deliver.window, location=deliver.location, ref="ak_deliver_pendant")
    plan = Plan(goal="x", steps=[step])
    gs = _gs(inventory=["Pendant of Memories"], quest_progress={"anju_kafei": "done"})
    assert validate_plan(plan, gs, [deliver], kb.npcs).valid


def test_required_item_provided_by_earlier_step_passes():
    """A required item is not flagged missing when an earlier step provides it."""
    first = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    second = TimeWindow(start=ClockTime(day=1, hour=9), end=ClockTime(day=1, hour=10))
    o1 = _objective("o1", first)
    o1.provides_items = ["Secret Letter"]
    o2 = _objective("o2", second)
    o2.requires_items = ["Secret Letter"]
    s1 = _step("s1", first, ref="o1")
    s2 = _step("s2", second, ref="o2")
    plan = Plan(goal="x", steps=[s1, s2])
    assert validate_plan(plan, _gs(), [o1, o2]).valid


def test_required_item_not_credited_when_provider_is_later():
    """A provider step after the need does not satisfy the requirement."""
    first = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    second = TimeWindow(start=ClockTime(day=1, hour=9), end=ClockTime(day=1, hour=10))
    o1 = _objective("o1", first)
    o1.requires_items = ["Secret Letter"]
    o2 = _objective("o2", second)
    o2.provides_items = ["Secret Letter"]
    s1 = _step("s1", first, ref="o1")
    s2 = _step("s2", second, ref="o2")
    plan = Plan(goal="x", steps=[s1, s2])
    result = validate_plan(plan, _gs(), [o1, o2])
    assert not result.valid
    assert any(i.kind == "item" for i in result.issues)


def test_knowledge_npc_schedules_and_events():
    """The knowledge base exposes NPC schedules, events and locations."""
    from app.data.mock_knowledge import build_default_knowledge

    kb = build_default_knowledge()
    assert kb.npc("anju").available_at(ClockTime(day=2, hour=9))
    assert not kb.npc("anju").available_at(ClockTime(day=1, hour=23))
    assert kb.event("ak_letter_delivery").name == "Kafei's letter is delivered"
    assert len(kb.locations) >= 6
    ak_deliver = next(o for q in kb.quests for o in q.objectives if o.id == "ak_deliver_pendant")
    assert ak_deliver.npc_id == "anju"


def test_objective_tool_failure_is_fail_closed(monkeypatch):
    """A failing objective lookup rejects the step instead of skipping it."""
    from app.agents import critic_knowledge

    def _boom(_ref):
        raise RuntimeError("knowledge backend down")

    monkeypatch.setattr(critic_knowledge, "get_objective", _boom)
    start = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    plan = Plan(goal="x", steps=[_step("s1", start, ref="ak_get_kafei_mask")])
    result = validate_plan(plan, _gs(), [])
    assert [i.kind for i in result.issues] == ["objective"]


def test_npc_tool_failure_does_not_block_the_plan(monkeypatch):
    """A failing schedule lookup degrades to no NPC check, not to a failure."""
    from app.agents import critic_knowledge

    def _boom(_npc_id):
        raise RuntimeError("knowledge backend down")

    monkeypatch.setattr(critic_knowledge, "get_npc_schedule", _boom)
    start = TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9))
    objective = _objective("o1", start)
    objective.npc_id = "anju"
    result = validate_plan(Plan(goal="x", steps=[_step("s1", start, ref="o1")]), _gs(), [objective])
    assert result.valid


def test_objective_lookups_are_cached_per_validation(monkeypatch):
    """A ref resolved twice reaches the tool only once."""
    from app.agents import critic_knowledge

    calls: list[str] = []
    real = critic_knowledge.get_objective

    def _counting(ref):
        calls.append(ref)
        return real(ref)

    monkeypatch.setattr(critic_knowledge, "get_objective", _counting)
    view = critic_knowledge.KnowledgeView()
    first = view.objective("ak_reunite")
    second = view.objective("ak_reunite")
    assert calls == ["ak_reunite"]
    assert first is second


def test_quest_lookups_are_cached_per_validation(monkeypatch):
    """A quest resolved twice reaches the tool only once."""
    from app.agents import critic_knowledge

    calls: list[str] = []
    real = critic_knowledge.get_quest_info

    def _counting(quest_id):
        calls.append(quest_id)
        return real(quest_id)

    monkeypatch.setattr(critic_knowledge, "get_quest_info", _counting)
    view = critic_knowledge.KnowledgeView()
    first = view.quest("anju_kafei")
    second = view.quest("anju_kafei")
    assert calls == ["anju_kafei"]
    assert first is second


def test_new_critic_messages_translate_to_italian():
    """The overlap and named-ref messages have Italian templates."""
    from unittest.mock import patch

    with patch("streamlit.session_state") as sess:
        sess.get.return_value = "it"
        from app.i18n import t, tr_msg

        assert (
            tr_msg("Overlaps the previous step, which ends at Day 1, 09:00.")
            == "Si sovrappone al passo precedente, che termina alle Day 1, 09:00."
        )
        assert (
            tr_msg("Unknown objective reference: 'not_a_real_objective'.")
            == "Riferimento obiettivo sconosciuto: 'not_a_real_objective'."
        )
        assert t("kind_overlap") == "sovrapposizione"
