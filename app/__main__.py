"""Headless demo of the full pipeline.

Run with ``uv run python -m app`` after configuring an LLM provider, or fully
offline with ``uv run python -m app --deterministic --no-rag``. Ollama can be
used for a local run without an external API key.
"""

from __future__ import annotations

import argparse
import logging
import os

from app.agents.planning_agent import PlanningAgentError
from app.domain import ClockTime, GameState, Goal
from app.graph import MAX_PLANNING_ATTEMPTS, run_pipeline
from app.llm import LLMConfigurationError
from app.log import configure_logging
from app.memory.models import PlayerPreferences
from app.state import PlanningState
from app.trace import current_run, setup_tracing

logger = logging.getLogger(__name__)


def demo(planner: str | None = None) -> PlanningState:
    """Run the headless Anju & Kafei demo and print the pipeline output.

    args:
        planner (str | None): per-run planner engine override (``"llm"`` or
            ``"deterministic"``); None uses the configured ``PLANNER``.

    returns:
        PlanningState: the finished run, so a caller can assert on it. A run
        that fails on LLM configuration or planning returns a state with no
        plan; the caller decides the exit code.
    """
    configure_logging()
    setup_tracing()
    game_state = GameState(
        time=ClockTime(day=1, hour=8, minute=0),
        location="Stockpot Inn",
        inventory=["Hookshot"],
        masks=["Garo's Mask"],
    )
    goal = Goal(description="Reunite Anju and Kafei before the dawn of the Third Day")

    print("Goal:", goal.description)
    print("Player:", game_state.model_dump())
    print("Memory: in-memory (preferences: completionist demo)")

    result = run_pipeline(
        game_state,
        goal,
        preferences=PlayerPreferences(playstyle="completionist"),
        planner=planner,
    )

    print("\n--- State Agent understood ---")
    print(result.state_summary)

    print(f"\n--- Memory ({result.memory_engine or 'in-memory'}) ---")
    if result.relevant_episodes:
        for ep in result.relevant_episodes:
            print(f"  - {ep.goal!r} valid={ep.valid}: {ep.plan_summary[:120]}")
    else:
        print("  No past episodes.")

    print("\n--- Knowledge Agent retrieved ---")
    print(result.retrieved_context)
    print(f"\nRAG engine: {result.retrieval_engine or 'unavailable'}")
    print(f"RAG status: {result.retrieval_status or 'unavailable'}")
    if result.retrieval_wiki_unreachable:
        print("RAG wiki: unreachable (using structured MCP data only)")
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
        source = metadata.display_url
        print(f"  - {metadata.title} [{evidence.chunk.id}] score={evidence.score:.3f}")
        print(f"    {source}")
        if metadata.source_revision_id:
            print(
                f"    revision {metadata.source_revision_id} ({metadata.source_revision_timestamp})"
            )

    plan_label = f"{result.replan_attempts} planning attempt(s) of max {MAX_PLANNING_ATTEMPTS}"
    print(f"\nPlanner engine: {result.plan_engine or 'llm'}")
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

    run = current_run()
    if run is not None:
        print(f"\n--- Trace (run {run.run_id}, {run.duration_s():.1f}s) ---")
        for node in run.nodes:
            print(
                f"  {node['name']:<14} {node['duration_s'] * 1000:8.1f} ms  {node['status']}"
                + (f"  ({node['detail']})" if node["detail"] else "")
            )
        for error in run.errors:
            print(f"  error [{error['source']}]: {error['message']}")

    print(
        "\nOutcome:"
        + (
            " feasible plan."
            if result.validation and result.validation.valid
            else " goal not reachable with this state."
        )
    )
    return result


def _parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the headless demo."""
    parser = argparse.ArgumentParser(description="Run the TaIA planning pipeline once, headless.")
    parser.add_argument(
        "--deterministic",
        action="store_true",
        help="skip the LLM and rebuild the objective chain deterministically",
    )
    parser.add_argument(
        "--no-rag",
        action="store_true",
        help="disable the supplemental wiki retrieval for this run",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print the full traceback when the pipeline fails unexpectedly",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the demo from the command line.

    args:
        argv (list[str] | None): arguments to parse; None uses ``sys.argv``.

    returns:
        int: 0 when the run produced a plan, 1 when planning failed.
    """
    args = _parser().parse_args(argv)
    previous_rag = os.environ.get("RAG_ENABLED")
    if args.no_rag:
        os.environ["RAG_ENABLED"] = "0"
    try:
        result = demo("deterministic" if args.deterministic else None)
    except (LLMConfigurationError, PlanningAgentError) as exc:
        print(f"\nPlanning failed: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - the CLI reports the failure, never a raw crash
        if args.debug:
            logger.exception("Headless demo failed")
        print(f"\nPlanning failed: {type(exc).__name__}: {exc}")
        return 1
    finally:
        if args.no_rag:
            if previous_rag is None:
                os.environ.pop("RAG_ENABLED", None)
            else:
                os.environ["RAG_ENABLED"] = previous_rag
    return 0 if result.plan else 1


if __name__ == "__main__":
    raise SystemExit(main())
