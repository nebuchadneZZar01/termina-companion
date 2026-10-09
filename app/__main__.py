"""Headless demo of the full pipeline.

Run with ``uv run python -m app`` after configuring an LLM provider. Ollama
can be used for a local run without an external API key.
"""

from __future__ import annotations

from app.agents.planning_agent import PlanningAgentError
from app.domain import ClockTime, GameState, Goal
from app.graph import MAX_PLANNING_ATTEMPTS, run_pipeline
from app.llm import LLMConfigurationError
from app.log import configure_logging


def demo() -> None:
    """Run the headless Anju & Kafei demo and print the pipeline output.

    args:
        (none)

    returns:
        None: prints the goal, state, retrieved context, plan and
        validation to stdout.
    """
    configure_logging()
    game_state = GameState(
        time=ClockTime(day=2, hour=8, minute=0),
        location="Stockpot Inn",
        inventory=["Kafei's Letter"],
    )
    goal = Goal(description="Reunite Anju and Kafei before the dawn of the Third Day")

    print("Goal:", goal.description)
    print("Player:", game_state.model_dump())

    try:
        result = run_pipeline(game_state, goal)
    except (LLMConfigurationError, PlanningAgentError) as exc:
        print(f"\nPlanning failed: {exc}")
        return

    print("\n--- State Agent understood ---")
    print(result.state_summary)

    print("\n--- Knowledge Agent retrieved ---")
    print(result.retrieved_context)
    print(f"\nRAG engine: {result.retrieval_engine or 'unavailable'}")
    print(f"RAG status: {result.retrieval_status or 'unavailable'}")
    if result.retrieval_ingested_pages:
        print(f"RAG pages ingested: {', '.join(result.retrieval_ingested_pages)}")
    if result.retrieval_indexed_sources:
        print("RAG indexed sources:")
        for source in result.retrieval_indexed_sources:
            page = "-" if source.source_page_id is None else str(source.source_page_id)
            revision = "-" if source.source_revision_id is None else str(source.source_revision_id)
            print(f"  - {source.title} [page={page}, revision={revision}]")
            if source.source_url:
                print(f"    revision URL: {source.source_url}")
            if source.canonical_url:
                print(f"    canonical URL: {source.canonical_url}")
            if source.license_note:
                print(f"    license: {source.license_note}")
            if source.license_url:
                print(f"    license URL: {source.license_url}")
            if source.retrieved_at:
                print(f"    retrieved at: {source.retrieved_at}")
    if result.retrieval_warning:
        print(f"RAG warning: {result.retrieval_warning}")
    for evidence in result.retrieved_evidence:
        metadata = evidence.chunk.metadata
        source = metadata.source_url or metadata.canonical_url or "Zelda Wiki"
        print(f"  - {metadata.title} [{evidence.chunk.id}] score={evidence.score:.3f}")
        print(f"    {source}")
        if metadata.source_revision_id:
            print(
                f"    revision {metadata.source_revision_id} ({metadata.source_revision_timestamp})"
            )

    plan_label = f"{result.replan_attempts} planning attempt(s) of max {MAX_PLANNING_ATTEMPTS}"
    print(f"\n--- Plan ({plan_label}) ---")
    if result.plan:
        for i, step in enumerate(result.plan.steps, 1):
            print(f"{i}. {step.window} {step.title} @ {step.location}")
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
