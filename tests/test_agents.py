"""Every agent reports which engine produced its output."""

import pytest

from app.agents import (
    critic_agent,
    knowledge_agent,
    planning_agent,
    planning_chain,
    planning_clock,
    planning_draft,
    state_agent,
)
from app.agents.planning_agent import PlanningAgentError
from app.data.mock_knowledge import Objective, build_default_knowledge
from app.domain import ClockTime, GameState, Goal, Plan, PlanStep, TimeWindow
from app.mcp.tools import search_quests
from app.state import PlanningState

_KB = build_default_knowledge()

_ANJU_CHAIN = [
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


def _relevant(description: str) -> list[Objective]:
    """Objectives matched by the MCP search tool for a goal text."""
    groups = search_quests(description)
    return [Objective.model_validate(obj) for group in groups for obj in group["objectives"]]


def _state(**kw) -> PlanningState:
    """Build a PlanningState on the Anju & Kafei quest for tests.

    args:
        kw (dict): extra GameState fields.

    returns:
        PlanningState: a state at Day 1 06:00 in the Stockpot Inn.
    """
    gs = GameState(time=ClockTime(day=1, hour=6), location="Stockpot Inn", **kw)
    return PlanningState(
        game_state=gs,
        goal=Goal(description="Reunite Anju and Kafei"),
        relevant_objectives=_relevant("kafei letter"),
    )


def test_state_agent_is_rule_based():
    """The State Agent reports the rule-based engine."""
    assert state_agent.run(_state())["state_engine"] == "rule-based"


def test_state_agent_summary_does_not_infer_a_quest_from_location():
    """The summary never guesses an active quest from the player's position."""
    summary = state_agent.run(_state())["state_summary"]
    assert "Active:" not in summary
    assert "Anju and Kafei" not in summary


def test_progress_summary_lists_completed_quest():
    """A quest marked done in quest_progress is reported as completed."""
    from app.agents.state_agent import _progress_summary

    kb = build_default_knowledge()
    out = _progress_summary({"anju_kafei": "done"}, kb)
    assert "Completed quests: Anju and Kafei" in out


def test_progress_summary_empty_without_completed_quests():
    """No progress is reported when no quest is completed."""
    from app.agents.state_agent import _progress_summary

    kb = build_default_knowledge()
    assert _progress_summary({}, kb) == ""


def test_knowledge_agent_is_rule_based():
    """The Knowledge Agent reports the rule-based engine."""
    assert knowledge_agent.run(_state())["knowledge_engine"] == "rule-based"


def test_critic_agent_is_rule_based():
    """The Critic Agent reports the rule-based engine."""
    assert critic_agent.run(_state())["critic_engine"] == "rule-based"


def test_critic_agent_records_one_attempt_per_run():
    """Each Critic run appends one attempt record to the log."""
    state = _state()

    first = critic_agent.run(state)
    assert len(first["attempt_log"]) == 1
    record = first["attempt_log"][0]
    assert record.valid is first["validation"].valid
    assert record.attempt == 1

    # A re-plan keeps the earlier records and appends the new one.
    second = critic_agent.run(state.model_copy(update={"attempt_log": first["attempt_log"]}))
    assert [r.attempt for r in second["attempt_log"]] == [1, 2]


def test_planning_agent_requires_llm(monkeypatch):
    """The Planning Agent fails explicitly when no LLM is available."""
    monkeypatch.setattr(planning_agent, "get_chat_model", lambda **kw: None)
    with pytest.raises(PlanningAgentError, match="requires a configured LLM"):
        planning_agent.run(_state())


def test_planning_agent_fails_clearly_without_objectives(monkeypatch):
    """No relevant objectives (e.g. a down knowledge tool) is named explicitly."""
    monkeypatch.setattr(planning_agent, "get_chat_model", lambda **kw: _FakeModel())
    state = _state()
    state.relevant_objectives = []
    with pytest.raises(PlanningAgentError, match="No relevant objectives"):
        planning_agent.run(state)


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
    window = TimeWindow(start=ClockTime(day=1, hour=24), end=ClockTime(day=1, hour=25))
    plan = _plan_step("lettera", "Laundry Pool", window)
    out = planning_chain._ground_llm_steps(plan, _state().relevant_objectives)
    assert out.steps[0].objective_ref == "ak_post_letter"
    assert out.steps[0].title == "Post the letter to Kafei in the Laundry Pool"


def test_ground_replaces_id_title_for_known_ref():
    """Grounding replaces a bare [id] title with the objective's title."""
    window = TimeWindow(start=ClockTime(day=1, hour=10), end=ClockTime(day=1, hour=11))
    plan = Plan(
        goal="x",
        steps=[
            PlanStep(
                title="[ak_get_kafei_mask]",
                objective_ref="ak_get_kafei_mask",
                location="Mayor's Residence",
                window=window,
            )
        ],
    )
    out = planning_chain._ground_llm_steps(plan, _state().relevant_objectives)
    assert out.steps[0].title == "Get Kafei's Mask from Madame Aroma"


def test_ground_leaves_unknown_untouched():
    """Grounding leaves unknown objective refs untouched."""
    window = TimeWindow(start=ClockTime(day=2, hour=9), end=ClockTime(day=2, hour=10))
    plan = _plan_step("mystery", "Nowhere", window)
    out = planning_chain._ground_llm_steps(plan, _state().relevant_objectives)
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
                objective_ref="ak_get_kafei_mask",
                location="Mayor's Residence",
                window=w,
            ),
            PlanStep(
                title="s2",
                objective_ref="ak_get_room_key",
                location="Stockpot Inn",
                window=w,
                depends_on=[0],
            ),
            PlanStep(
                title="s3 dup",
                objective_ref="ak_get_room_key",
                location="Stockpot Inn",
                window=w,
                depends_on=[1],
            ),
            PlanStep(title="s4 no ref", location="Q", window=w, depends_on=[2]),
        ],
    )
    out = planning_chain._dedupe_steps(plan)
    assert [s.objective_ref for s in out.steps] == [
        "ak_get_kafei_mask",
        "ak_get_room_key",
        "",
    ]
    assert out.steps[1].depends_on == [0]
    assert out.steps[2].depends_on == []  # dep pointed at the dropped duplicate


class _FakeModel:
    _invoked: list = []
    model_name = "fake-model"

    def with_structured_output(self, _schema):
        """Pretend to bind a structured-output schema and return self."""
        return self

    def invoke(self, msgs, **_kwargs):
        """Capture the prompt and return a canned grounded Plan."""
        _FakeModel._invoked = msgs
        mask_window = TimeWindow(start=ClockTime(day=1, hour=10), end=ClockTime(day=1, hour=11))
        key_window = TimeWindow(
            start=ClockTime(day=1, hour=13, minute=50),
            end=ClockTime(day=1, hour=14, minute=50),
        )
        return Plan(
            goal="x",
            steps=[
                PlanStep(
                    title="[ak_get_kafei_mask]",
                    objective_ref="ak_get_kafei_mask",
                    location="mayor_residence",
                    window=mask_window,
                ),
                PlanStep(
                    title="a step",
                    objective_ref="ak_get_room_key",
                    location="Stockpot Inn",
                    window=key_window,
                    depends_on=[0],
                ),
                PlanStep(
                    title="duplicate",
                    objective_ref="ak_get_room_key",
                    location="Stockpot Inn",
                    window=key_window,
                    depends_on=[1],
                ),
            ],
        )


class _EmptyModel:
    model_name = "empty-model"

    def with_structured_output(self, _schema):
        return self

    def invoke(self, _msgs, **_kwargs):
        return Plan(goal="x", steps=[])


def test_planning_agent_rebuilds_chain_from_empty_llm_plan(monkeypatch):
    """An empty LLM response still yields the deterministic objective chain."""
    monkeypatch.setattr(planning_agent, "get_chat_model", lambda **kw: _EmptyModel())
    result = planning_agent.run(_state())
    assert [s.objective_ref for s in result["plan"].steps] == _ANJU_CHAIN
    assert result["plan_proposal"].steps == []


def test_planning_agent_rejects_empty_plan_when_chain_is_done(monkeypatch):
    """Empty LLM output is a failure when no objective remains to rebuild."""
    monkeypatch.setattr(planning_agent, "get_chat_model", lambda **kw: _EmptyModel())
    state = _state(
        inventory=["Room Key", "Letter to Kafei", "Pendant of Memories", "Sun's Mask"],
        masks=["Kafei's Mask", "Garo's Mask", "Couple's Mask"],
    )
    with pytest.raises(PlanningAgentError, match="empty plan"):
        planning_agent.run(state)


def test_planning_agent_skips_owned_provide_step(monkeypatch):
    """The mask-acquisition step is pruned once the player already owns it."""
    monkeypatch.setattr(planning_agent, "get_chat_model", lambda **kw: _FakeModel())
    result = planning_agent.run(_state(masks=["Kafei's Mask"]))
    refs = [s.objective_ref for s in result["plan"].steps]
    assert refs == [
        "ak_get_room_key",
        "ak_talk_to_anju",
        "ak_meet_in_kitchen",
        "ak_post_letter",
        "ak_meet_kafei",
        "ak_deliver_pendant",
        "ak_sakon_hideout",
        "ak_reunite",
    ]
    assert result["plan"].steps[0].depends_on == []  # its prerequisite was pruned


def test_reconcile_orders_and_completes_chain():
    """Reconciling inserts chain steps the generator skipped, in prerequisite order."""
    window = TimeWindow(start=ClockTime(day=3, hour=28), end=ClockTime(day=3, hour=29))
    plan = Plan(goal="x", steps=[_plan_step("ak_reunite", "Stockpot Inn", window).steps[0]])
    out = planning_chain._reconcile_plan(plan, _state())
    refs = [s.objective_ref for s in out.steps]
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
    assert [s.depends_on for s in out.steps] == [
        [],
        [0],
        [1],
        [2],
        [3],
        [4],
        [5],
        [6],
        [7],
    ]


def test_reconcile_starts_after_the_furthest_owned_reward():
    """Owning a mid-chain reward prunes it and every objective before it."""
    state = _state(inventory=["Letter to Kafei", "Hookshot"], masks=["Garo's Mask"])
    out = planning_chain._reconcile_plan(Plan(goal="x"), state)
    assert [s.objective_ref for s in out.steps] == [
        "ak_post_letter",
        "ak_meet_kafei",
        "ak_deliver_pendant",
        "ak_sakon_hideout",
        "ak_reunite",
    ]
    assert out.steps[0].depends_on == []


def test_reconcile_skips_traded_away_rewards():
    """A traded-away reward still marks its objective and ancestors as done."""
    state = _state(inventory=["Mountain Title Deed"]).model_copy(
        update={
            "goal": Goal(description="Trade the title deeds"),
            "relevant_objectives": _relevant("title deed"),
        }
    )
    out = planning_chain._reconcile_plan(Plan(goal="x"), state)
    assert [s.objective_ref for s in out.steps] == [
        "dc_mountain_to_bay",
        "dc_ocean_to_rupee",
    ]


def test_reconcile_prunes_each_quest_independently():
    """An owned reward only shortens its own quest's chain."""
    state = _state(inventory=["Letter to Kafei", "Hookshot"], masks=["Garo's Mask"]).model_copy(
        update={
            "goal": Goal(description="Reunite Anju and Kafei and trade the deeds"),
            "relevant_objectives": _relevant("title deed") + _relevant("kafei letter"),
        }
    )
    out = planning_chain._reconcile_plan(Plan(goal="x"), state)
    refs = [s.objective_ref for s in out.steps]
    assert "ak_get_kafei_mask" not in refs
    assert "dc_get_moon_tear" in refs


def test_reconcile_keeps_requirements_the_inventory_does_not_cover():
    """An inconsistent inventory falls back to acquiring the missing mask."""
    state = _state(inventory=["Pendant of Memories"])
    out = planning_chain._reconcile_plan(Plan(goal="x"), state)
    refs = [s.objective_ref for s in out.steps]
    assert refs[0] == "ak_get_kafei_mask"
    assert "ak_meet_kafei" not in refs  # its reward is already owned


def test_planning_agent_llm_plan_is_grounded(monkeypatch):
    """An LLM-produced plan is grounded and completed to the full chain."""
    monkeypatch.setattr(planning_agent, "get_chat_model", lambda **kw: _FakeModel())
    result = planning_agent.run(_state())
    assert result["plan_engine"] == "llm"
    assert result["plan_model"] == "fake-model"
    refs = [s.objective_ref for s in result["plan"].steps]
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
    step = result["plan"].steps[1]
    assert step.title == "Get the Stockpot Inn room key from Anju"
    assert step.location == "Stockpot Inn"
    assert step.requires_items == []  # the key is provided, not required
    assert step.depends_on == [0]


def test_planning_agent_keeps_the_raw_proposal(monkeypatch):
    """The proposal is the LLM's own answer, before grounding and repair."""
    monkeypatch.setattr(planning_agent, "get_chat_model", lambda **kw: _FakeModel())

    result = planning_agent.run(_state())

    proposal = result["plan_proposal"]
    assert proposal is not result["plan"]
    assert [s.objective_ref for s in proposal.steps] == [
        "ak_get_kafei_mask",
        "ak_get_room_key",
        "ak_get_room_key",
    ]
    assert proposal.steps[0].title == "[ak_get_kafei_mask]", "the proposal must stay untouched"
    assert len(result["plan"].steps) == 9, "the reconciled plan is grounded and deduped"


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
    out = planning_chain._clamp_windows(plan, _state().relevant_objectives)
    assert out.steps[0].objective_ref == "ak_talk_to_anju"
    assert out.steps[0].window.start == ClockTime(day=1, hour=14, minute=20)
    assert out.steps[0].window.end == ClockTime(day=1, hour=21, minute=5)


def test_clamp_windows_falls_back_when_window_is_disjoint():
    """A window fully outside the slot falls back inside the objective's."""
    w = TimeWindow(start=ClockTime(day=1, hour=10), end=ClockTime(day=1, hour=11))
    plan = _plan_step("ak_sakon_hideout", "Sakon's Hideout", w)
    state = _state()
    out = planning_chain._clamp_windows(plan, state.relevant_objectives)
    obj = next(o for o in state.relevant_objectives if o.id == "ak_sakon_hideout")
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
    out = planning_chain._clamp_windows(plan, _state().relevant_objectives)
    assert out.steps[0].window == w


def test_ground_replaces_invented_location():
    """Grounding replaces an invented location and fills requirements."""
    window = TimeWindow(start=ClockTime(day=2, hour=15), end=ClockTime(day=2, hour=16))
    plan = Plan(
        goal="x",
        steps=[
            PlanStep(
                title="[ak_deliver_pendant]",
                objective_ref="ak_deliver_pendant",
                location="stockpot_inn",
                window=window,
            )
        ],
    )
    out = planning_chain._ground_llm_steps(plan, _state().relevant_objectives)
    assert out.steps[0].location == "Stockpot Inn"
    assert out.steps[0].requires_items == ["Pendant of Memories"]


def test_reconcile_re_slots_every_step_on_replan():
    """On replan, every window is re-slotted into 1h, dependency-ordered."""
    state = _state().model_copy(update={"replan_attempts": 1})
    out = planning_chain._reconcile_plan(_slot_width_plan(), state)
    assert [s.objective_ref for s in out.steps] == _ANJU_CHAIN
    assert [s.depends_on for s in out.steps] == [
        [],
        [0],
        [1],
        [2],
        [3],
        [4],
        [5],
        [6],
        [7],
    ]
    assert out.steps[0].window == TimeWindow(
        start=ClockTime(day=1, hour=10), end=ClockTime(day=1, hour=11)
    )
    assert out.steps[1].window == TimeWindow(
        start=ClockTime(day=1, hour=13, minute=50),
        end=ClockTime(day=1, hour=14, minute=50),
    )
    assert out.steps[2].window == TimeWindow(
        start=ClockTime(day=1, hour=14, minute=50),
        end=ClockTime(day=1, hour=15, minute=50),
    )
    start = out.steps[-1].window.start
    end = out.steps[-2].window.end
    assert (start.day, start.hour, start.minute) >= (end.day, end.hour, end.minute)


def _slot_width_plan() -> Plan:
    """A plan whose steps span their whole objective slot, as a weak LLM writes it.

    args:
        (none)

    returns:
        Plan: the Anju & Kafei chain with full-slot windows.
    """
    return Plan(
        goal="x",
        steps=[
            _plan_step(objective.id, objective.location, objective.window).steps[0]
            for objective in _state().relevant_objectives
        ],
    )


def test_reconcile_keeps_a_window_that_fits_the_chain():
    """A window that respects the chain is kept, the LLM's timing survives."""
    plan = Plan(
        goal="x",
        steps=[
            _plan_step(
                "ak_post_letter",
                "Laundry Pool",
                TimeWindow(start=ClockTime(day=1, hour=25), end=ClockTime(day=1, hour=26)),
            ).steps[0],
            _plan_step(
                "ak_deliver_pendant",
                "Stockpot Inn",
                TimeWindow(start=ClockTime(day=2, hour=17), end=ClockTime(day=2, hour=18)),
            ).steps[0],
        ],
    )
    out = planning_chain._reconcile_plan(plan, _state())
    by_ref = {step.objective_ref: step for step in out.steps}

    assert by_ref["ak_post_letter"].window == TimeWindow(
        start=ClockTime(day=1, hour=25), end=ClockTime(day=1, hour=26)
    )
    assert by_ref["ak_deliver_pendant"].window == TimeWindow(
        start=ClockTime(day=2, hour=17), end=ClockTime(day=2, hour=18)
    )


def test_reconcile_re_slots_a_window_that_would_starve_its_successor():
    """A window ending after the successor's slot opens is re-slotted."""
    out = planning_chain._reconcile_plan(_slot_width_plan(), _state())

    assert out.steps[0].window == TimeWindow(
        start=ClockTime(day=1, hour=10), end=ClockTime(day=1, hour=11)
    )


def test_reconciled_plan_has_no_sequence_conflict():
    """After the rebuild no step starts before a dependency ends."""
    out = planning_chain._reconcile_plan(_slot_width_plan(), _state())

    def _at(time: ClockTime) -> tuple[int, int, int]:
        return (time.day, time.hour, time.minute)

    for idx, step in enumerate(out.steps):
        for dep in step.depends_on:
            assert _at(out.steps[dep].window.end) <= _at(step.window.start)
        if idx:
            assert _at(out.steps[idx - 1].window.end) <= _at(step.window.start)


def test_critic_accepts_a_reconciled_slot_width_plan():
    """The whole-slot plan a weak LLM writes is feasible once rebuilt."""
    state = _state()
    out = planning_chain._reconcile_plan(_slot_width_plan(), state)

    result = critic_agent.run(state.model_copy(update={"plan": out}))

    kinds = {issue.kind for issue in result["validation"].issues}
    assert "sequence" not in kinds
    assert "overlap" not in kinds


def test_sanitize_window_passes_valid_window_through():
    """A valid raw window is kept as-is, not rescheduled."""
    w = planning_draft._DraftTimeWindow(
        start=ClockTime(day=3, hour=22), end=ClockTime(day=3, hour=23)
    )
    out = planning_draft._sanitize_window(w, None)
    assert out == TimeWindow(start=ClockTime(day=3, hour=22), end=ClockTime(day=3, hour=23))


def test_sanitize_window_anchors_degenerate_window_to_slot():
    """A zero-length window at the cycle end is pinned to the objective slot."""
    w = planning_draft._DraftTimeWindow(
        start=ClockTime(day=3, hour=29, minute=59),
        end=ClockTime(day=3, hour=29, minute=59),
    )
    obj = next(o for q in _KB.quests for o in q.objectives if o.id == "ak_reunite")
    out = planning_draft._sanitize_window(w, obj)
    assert out == obj.window  # [Day 3 04:00 (+1) -> Day 3 05:00 (+1)]


def test_sanitize_window_returns_valid_window_when_ungrounded():
    """An ungrounded degenerate window still yields a structurally valid one."""
    w = planning_draft._DraftTimeWindow(
        start=ClockTime(day=3, hour=29, minute=59),
        end=ClockTime(day=3, hour=29, minute=59),
    )
    out = planning_draft._sanitize_window(w, None)
    assert (out.start.day, out.start.hour, out.start.minute) < (
        out.end.day,
        out.end.hour,
        out.end.minute,
    )


def test_materialize_plan_builds_strict_plan_from_draft():
    """Materializing a draft plan copies fields and repairs degenerate windows."""
    draft = planning_draft._DraftPlan(
        goal="g",
        steps=[
            planning_draft._DraftPlanStep(
                title="Reunite",
                objective_ref="ak_reunite",
                location="Stockpot Inn",
                window=planning_draft._DraftTimeWindow(
                    start=ClockTime(day=3, hour=29, minute=59),
                    end=ClockTime(day=3, hour=29, minute=59),
                ),
                depends_on=[0],
            ),
            planning_draft._DraftPlanStep(
                title="Erratic",
                objective_ref="mystery",
                location="Nowhere",
                window=planning_draft._DraftTimeWindow(
                    start=ClockTime(day=1, hour=0), end=ClockTime(day=1, hour=0)
                ),
            ),
        ],
    )
    out = planning_draft._materialize_plan(draft, _state())
    assert isinstance(out, Plan)
    obj = next(o for q in _KB.quests for o in q.objectives if o.id == "ak_reunite")
    assert out.steps[0].window == obj.window
    assert out.steps[0].depends_on == [0]
    assert (
        out.steps[1].window.start.day,
        out.steps[1].window.start.hour,
        out.steps[1].window.start.minute,
    ) < (
        out.steps[1].window.end.day,
        out.steps[1].window.end.hour,
        out.steps[1].window.end.minute,
    )
    assert all(
        (s.window.start.day, s.window.start.hour, s.window.start.minute)
        < (s.window.end.day, s.window.end.hour, s.window.end.minute)
        for s in out.steps
    )


def test_window_inside_handles_earliest_at_cycle_end():
    """A dependency ending at the cycle end never yields an invalid window."""
    obj = next(o for q in _KB.quests for o in q.objectives if o.id == "ak_reunite")
    out = planning_clock._window_inside(obj, ClockTime(day=3, hour=29, minute=59))
    assert (out.start.day, out.start.hour, out.start.minute) < (
        out.end.day,
        out.end.hour,
        out.end.minute,
    )
    assert (out.start.day, out.start.hour, out.start.minute) >= (
        obj.window.start.day,
        obj.window.start.hour,
        obj.window.start.minute,
    )


class _DegenerateWindowModel:
    """Fake model returning a degenerate cycle-end window as raw JSON."""

    model_name = "degenerate-window-model"

    def with_structured_output(self, _schema):
        return self

    def invoke(self, _msgs, **_kwargs):
        return {
            "goal": "Reunite Anju and Kafei",
            "steps": [
                {
                    "title": "Reunite",
                    "objective_ref": "ak_reunite",
                    "location": "Stockpot Inn",
                    "window": {
                        "start": {"day": 3, "hour": 29, "minute": 59},
                        "end": {"day": 3, "hour": 29, "minute": 59},
                    },
                    "depends_on": [],
                }
            ],
        }


def test_planning_agent_repairs_degenerate_cycle_end_window(monkeypatch):
    """A zero-length window at the cycle end plans instead of failing validation."""
    monkeypatch.setattr(planning_agent, "get_chat_model", lambda **kw: _DegenerateWindowModel())
    result = planning_agent.run(_state())
    step = next(s for s in result["plan"].steps if s.objective_ref == "ak_reunite")
    start, end = step.window.start, step.window.end
    assert (start.day, start.hour, start.minute) < (end.day, end.hour, end.minute)
    assert start == ClockTime(day=3, hour=28)  # pinned to the slot start
    assert end == ClockTime(day=3, hour=29)


def test_to_step_carries_requires_masks():
    """_to_step carries an objective's required masks into the step."""
    obj = next(o for q in _KB.quests for o in q.objectives if o.id == "ak_talk_to_anju")
    step = planning_chain._to_step(
        obj, TimeWindow(start=ClockTime(day=1, hour=8), end=ClockTime(day=1, hour=9)), []
    )
    assert step.requires_masks == ["Kafei's Mask"]


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


def test_progress_report_is_a_noop_without_a_stream():
    """Reporting progress outside a graph stream must never raise."""
    from app.progress import report

    report({"node": "state", "phase": "start"})
