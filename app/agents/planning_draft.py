"""LLM-facing draft schema and strict plan materialization."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.planning_clock import _draft_fallback_window, _max_clock
from app.data.mock_knowledge import Objective
from app.domain import ClockTime, Plan, PlanStep, TimeWindow
from app.domain import clock_key as _clock
from app.state import PlanningState


# The `_Draft*` models are the LLM-facing structured-output schema. They mirror
# the authoritative `Plan`/`PlanStep`/`TimeWindow` contracts but WITHOUT the
# cross-field `end must be after start` validator: raw LLM windows may be
# degenerate (e.g. a zero-length window at the last cycle instant, Day 3
# 29:59), and rejecting them during parsing would bypass the deterministic
# repair below. Every draft window is sanitized by `_sanitize_window` before a
# strict `Plan` is built.
class _DraftTimeWindow(BaseModel):
    start: ClockTime
    end: ClockTime


class _DraftPlanStep(BaseModel):
    title: str
    objective_ref: str = ""
    location: str
    window: _DraftTimeWindow
    actions: list[str] = Field(default_factory=list)
    requires_items: list[str] = Field(default_factory=list)
    requires_masks: list[str] = Field(default_factory=list)
    depends_on: list[int] = Field(default_factory=list)


class _DraftPlan(BaseModel):
    goal: str
    steps: list[_DraftPlanStep] = Field(default_factory=list)


def _materialize_plan(raw, state: PlanningState) -> Plan:
    """Turn raw LLM output into a strict Plan with structurally valid windows.

    Accepts a strict ``Plan`` (already valid, e.g. from test doubles or simple
    reroutes), a ``_DraftPlan`` or a plain dict/JSON object. Draft steps are
    copied field-by-field and every window is sanitized by ``_sanitize_window``
    so the authoritative ``Plan``/``TimeWindow`` contracts never reject the
    LLM output.

    args:
        raw: the structured-output result from the model.
        state (PlanningState): used only for the relevant objectives, which
        anchor degenerate windows into their slot.

    returns:
        Plan: a strict, valid plan.

    raises:
        pydantic.ValidationError: when ``raw`` is not a usable plan shape.
    """
    if isinstance(raw, Plan):
        return raw
    if not isinstance(raw, _DraftPlan):
        raw = _DraftPlan.model_validate(raw)
    by_id = {o.id: o for o in state.relevant_objectives}
    steps = [
        PlanStep(
            title=step.title,
            objective_ref=step.objective_ref,
            location=step.location,
            window=_sanitize_window(step.window, by_id.get(step.objective_ref)),
            actions=step.actions,
            requires_items=step.requires_items,
            requires_masks=step.requires_masks,
            depends_on=step.depends_on,
        )
        for step in raw.steps
    ]
    return Plan(goal=raw.goal, steps=steps)


def _sanitize_window(window: _DraftTimeWindow, obj: Objective | None) -> TimeWindow:
    """Repair a raw LLM window into a strict ``TimeWindow``, deterministically.

    Valid windows pass through unchanged. Degenerate windows (end not later
    than start, e.g. a zero-length window at the last instant of the cycle)
    are anchored back inside their objective's slot; steps without a resolvable
    objective get a minimal valid window and are pruned later by
    ``_reconcile_plan`` anyway.

    args:
        window (_DraftTimeWindow): the raw window from the LLM.
        obj (Objective): the objective the step's ref points at, or None.

    returns:
        TimeWindow: a window with ``end`` strictly after ``start``.
    """
    if _clock(window.start) < _clock(window.end):
        return TimeWindow(start=window.start, end=window.end)
    if obj is not None:
        start = _max_clock(window.start, obj.window.start)
        end = min(window.end, obj.window.end, key=_clock)
        if _clock(start) < _clock(end):
            return TimeWindow(start=start, end=end)
        # Degenerate even inside the slot (the LLM crammed the step into the
        # last instant of a slot that ends Day 3 29:59): fall back to the whole
        # authoritative slot, which is always valid in the knowledge base.
        return TimeWindow(start=obj.window.start, end=obj.window.end)
    return _draft_fallback_window(window.start)
