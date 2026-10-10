"""Calibrate the RAG similarity threshold on live wiki scenarios.

Usage:
    uv run python scripts/calibrate_rag.py --thresholds 0.60 0.72 0.80 --top-k 4 8

Runs the grid against CALIBRATION_SCENARIOS with an empty temp Qdrant dir
(never touches .cache/), prints hit_rate per combo to stdout and writes no
files. A wiki_unreachable combo means the wiki leg failed; planning still
works on MCP data, rerun later. Only Qdrant/embedding failures are
unavailable. This is a one-off maintainer step, not part of pytest or app
startup.
"""

from __future__ import annotations

import argparse
import tempfile

from app.rag.embeddings import get_embedding_provider
from app.rag.evaluation import evaluate_retrieval
from app.rag.retriever import AdaptiveRetriever, RAGSettings
from app.rag.scenarios import CALIBRATION_SCENARIOS
from app.rag.store import QdrantVectorStore
from app.rag.wiki import MediaWikiClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--thresholds", nargs="+", type=float, default=[0.60, 0.72, 0.80])
    parser.add_argument("--top-k", nargs="+", type=int, default=[4])
    parser.add_argument("--max-per-source", type=int, default=2)
    parser.add_argument("--embedding", choices=["fastembed", "hash"], default="fastembed")
    return parser.parse_args()


def run_grid(
    thresholds: list[float], top_ks: list[int], max_per_source: int, embedding: str
) -> int:
    failures = 0
    for threshold in thresholds:
        for top_k in top_ks:
            with tempfile.TemporaryDirectory(prefix="termina-calib-") as tmpdir:
                settings = RAGSettings(
                    qdrant_path=tmpdir,  # type: ignore[arg-type]
                    similarity_threshold=threshold,
                    top_k=top_k,
                    max_chunks_per_source=max_per_source,
                )
                provider = get_embedding_provider(
                    embedding,
                    model_name=settings.embedding_model,
                )
                store = QdrantVectorStore(
                    path=settings.qdrant_path,
                    collection_name=settings.collection_name,
                    dimensions=provider.dimensions,
                )
                wiki = MediaWikiClient(timeout_seconds=settings.request_timeout_seconds)
                retriever = AdaptiveRetriever(store, wiki, provider, settings)
                try:
                    report = evaluate_retrieval(retriever, CALIBRATION_SCENARIOS)
                finally:
                    retriever.close()
                unreachable = sum(s.wiki_unreachable for s in report.scenarios)
                print(
                    f"{threshold:.2f} top_k={top_k} -> "
                    f"{report.hits}/{report.total} = {report.hit_rate:.2f} "
                    f"(unavailable={report.unavailable}, wiki_unreachable={unreachable})"
                )
                for scenario in report.scenarios:
                    if not scenario.hit:
                        print(f"  miss: {scenario.scenario_id} [{scenario.status}]")
                if report.unavailable:
                    failures += 1
    best = max(thresholds)
    print(f"done. Update CALIBRATED_* in app/rag/scenarios.py with the best combo (start: {best}).")
    return 1 if failures else 0


def main() -> None:
    args = parse_args()
    raise SystemExit(run_grid(args.thresholds, args.top_k, args.max_per_source, args.embedding))


if __name__ == "__main__":
    main()
