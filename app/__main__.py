"""Headless demo of the full pipeline, no API keys needed.

Run with ``uv run python -m app``.
"""

from __future__ import annotations

from app.domain import ClockTime, GameState, Goal
from app.graph import MAX_PLANNING_ATTEMPTS, run_pipeline
from app.log import configure_logging


def demo() -> None:
    configure_logging()
    game_state = GameState(
        time=ClockTime(day=2, hour=8, minute=0),
        location="Stockpot Inn",
        inventory=["Kafei's Letter"],
    )
    goal = Goal(description="Reunite Anju and Kafei before the dawn of the Third Day")

    print("Goal:", goal.description)
    print("Player:", game_state.model_dump())

    result = run_pipeline(game_state, goal)

    print("\n--- State Agent understood ---")
    print(result.state_summary)

    print("\n--- Knowledge Agent retrieved ---")
    print(result.retrieved_context)

    plan_label = f"{result.replan_attempts} planning attempt(s) of max {MAX_PLANNING_ATTEMPTS}"
    print(f"\n--- Plan ({plan_label}) ---")
    if result.plan:
        for i, step in enumerate(result.plan.steps, 1):
            print(f"{i}. [{step.window}] {step.title} @ {step.location}")
            print(f"   dep: {step.depends_on or 'start'}")
            if step.requires_items:
                print(f"   needs: {', '.join(step.requires_items)}")

    print("\n--- Validation ---")
    if result.validation:
        print("Valid!" if result.validation.valid else "Invalid:")
        for issue in result.validation.issues:
            print(f"  - [{issue.severity} / {issue.kind}] {issue.message}")

    print(
        "\nOutcome:"
        + (
            " feasible plan."
            if result.validation and result.validation.valid
            else " goal not reachable with this state."
        )
    )


if __name__ == "__main__":
    demo()
