"""Evaluate the plans produced by the pipeline against the shipped scenarios.

Usage:
    uv run python scripts/evaluate_plans.py
    uv run python scripts/evaluate_plans.py --scenario anju-kafei --repeat 3
    uv run python scripts/evaluate_plans.py --rag off
    uv run python scripts/evaluate_plans.py --json reports/evaluation.json
    uv run python scripts/evaluate_plans.py --list

Runs the full pipeline once per scenario (an LLM provider must be configured,
like the rest of the app), evaluates the produced plan against the scenario's
expectations and prints an explicit PASS/FAIL plus the aggregate pass rate.
The exit code is 1 when any scenario fails, so the harness can gate a run.

The memory store is cleared before every scenario, so the scenarios never see
each other's past episodes and stay independent. ``--rag off`` disables the
supplemental wiki retrieval (``RAG_ENABLED=0``) to compare plan quality with
and without it.

The same sweep runs in the *Evaluation* tab of the Streamlit UI: both entry
points share ``app.evaluation.runner``.

Every run also writes the report to the shared store (``app.evaluation.storage``,
next to the game-state save), so the checks outlive the process; ``--json``
writes an extra copy at an explicit path.

This is a maintainer tool: it needs an LLM and is not part of pytest.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.models import EvaluationReport, PlanScenario, ScenarioResult  # noqa: E402
from app.evaluation.runner import run_scenarios  # noqa: E402
from app.evaluation.scenarios import EVALUATION_SCENARIOS, SCENARIOS_BY_ID  # noqa: E402
from app.evaluation.storage import save_report  # noqa: E402
from app.log import configure_logging  # noqa: E402
from app.trace import setup_tracing  # noqa: E402


def parse_args() -> argparse.Namespace:
    """Parse the command-line arguments.

    args:
        (none)

    returns:
        argparse.Namespace: the parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        metavar="ID",
        help="Scenario id to run; repeatable. Defaults to every scenario.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="How many times to run each scenario (the planner is not deterministic).",
    )
    parser.add_argument(
        "--rag",
        choices=["on", "off"],
        default="on",
        help="Enable or disable the supplemental wiki retrieval.",
    )
    parser.add_argument("--json", metavar="PATH", default="", help="Write the report as JSON.")
    parser.add_argument("--list", action="store_true", help="List the scenarios and exit.")
    return parser.parse_args()


def select_scenarios(ids: list[str]) -> list[PlanScenario]:
    """Pick the scenarios to run.

    args:
        ids (list[str]): the requested scenario ids; empty means all.

    returns:
        list[PlanScenario]: the selected scenarios.
    """
    if not ids:
        return list(EVALUATION_SCENARIOS)
    unknown = [sid for sid in ids if sid not in SCENARIOS_BY_ID]
    if unknown:
        raise SystemExit(f"Unknown scenario(s): {', '.join(unknown)}")
    return [SCENARIOS_BY_ID[sid] for sid in ids]


def print_result(index: int, total: int, scenario: PlanScenario, result: ScenarioResult) -> None:
    """Print one scenario outcome.

    args:
        index (int): the 1-based position of the scenario in the run.
        total (int): the number of scenarios in the run.
        scenario (PlanScenario): the scenario that was run.
        result (ScenarioResult): its outcome.

    returns:
        None: prints to stdout.
    """
    status = "PASS" if result.passed else "FAIL"
    print(f"[{index}/{total}] {scenario.id:<22} {status}  ({result.duration_s:.1f}s)")
    if result.error:
        print(f"        run error: {result.error}")
    for issue in result.issues:
        marker = "error" if issue.severity == "error" else "warn "
        print(f"        - [{marker}/{issue.kind}] {issue.message}")
    if result.objective_refs:
        print(f"        steps: {result.step_count} -> {', '.join(result.objective_refs)}")


def print_summary(report: EvaluationReport) -> None:
    """Print the aggregate metrics of an evaluation run.

    args:
        report (EvaluationReport): the aggregated report.

    returns:
        None: prints to stdout.
    """
    print()
    print(
        f"Sweep: model={report.models or 'unknown'} wiki_retrieval={report.wiki_retrieval} "
        f"repeats={report.repeats}"
    )
    if report.wiki_retrieval == "degraded":
        print(
            "        wiki retrieval degraded during the run — see the per-scenario "
            "retrieval_status before comparing sweeps."
        )
    print(f"Pass rate: {report.passed}/{report.total} = {report.pass_rate:.2f}")
    kinds = report.failures_by_kind
    if kinds:
        print("Failures by check: " + ", ".join(f"{kind}={count}" for kind, count in kinds.items()))
    else:
        print("Failures by check: none")


def main() -> int:
    """Run the evaluation sweep and report the outcome.

    args:
        (none)

    returns:
        int: 0 when every scenario passed, 1 otherwise.
    """
    args = parse_args()
    if args.list:
        for scenario in EVALUATION_SCENARIOS:
            print(f"{scenario.id:<22} {scenario.name:<28} {scenario.description}")
        return 0

    configure_logging()
    setup_tracing()

    try:
        scenarios = select_scenarios(args.scenario)
    except SystemExit as exc:
        print(str(exc))
        return 1

    repeats = max(args.repeat, 1)
    total = len(scenarios) * repeats
    index = 0
    results: list[ScenarioResult] = []

    def _progress(scenario: PlanScenario, result: ScenarioResult) -> None:
        """Print one scenario outcome as soon as it is evaluated."""
        nonlocal index
        index += 1
        print_result(index, total, scenario, result)

    for _ in range(repeats):
        report = run_scenarios(scenarios, rag_on=args.rag == "on", on_progress=_progress)
        results.extend(report.results)

    report = EvaluationReport(results=results, rag_on=args.rag == "on", repeats=repeats)
    print_summary(report)

    try:
        saved = save_report(report)
    except Exception as exc:  # noqa: BLE001 - an unwritable store must not mask the exit code
        print(f"Could not save the last report: {exc}")
    else:
        print(f"Last report saved to {saved}")

    if args.json:
        path = Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        print(f"Report written to {path}")

    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
