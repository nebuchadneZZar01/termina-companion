"""Persistence for the evaluation reports.

The checks produced by a sweep (one PASS/FAIL per scenario) are worth
keeping after the run: the Streamlit UI and the CLI harness both write the
last report here and read it back, so a sweep can be reviewed later or
compared with a previous one.

The reports live next to the game-state save file, in the same directory
derived from ``RAG_QDRANT_PATH`` (see :func:`app.save.get_save_dir`), which is
ignored by git: the artifacts stay local unless they are copied out.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from app.evaluation.models import EvaluationReport
from app.save import get_save_dir

LAST_REPORT_NAME = "last_evaluation.json"
HISTORY_DIR_NAME = "evaluations"


def get_eval_dir() -> Path:
    """Return the directory where the evaluation reports are stored.

    args:
        (none)

    returns:
        Path: the report directory, created when missing.
    """
    return get_save_dir()


def get_history_dir() -> Path:
    """Return the directory holding the timestamped report history.

    args:
        (none)

    returns:
        Path: the history directory, created when missing.
    """
    path = get_eval_dir() / HISTORY_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _timestamp() -> str:
    """Return the current UTC timestamp used to name history files.

    args:
        (none)

    returns:
        str: the timestamp, e.g. ``20261021T143211Z``.
    """
    return datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")


def _write(path: Path, payload: str) -> None:
    """Write a file atomically, so a crash never leaves a truncated report.

    args:
        path (Path): the file to write.
        payload (str): the file content.

    returns:
        None: writes the file.
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def save_report(report: EvaluationReport, *, history: bool = True) -> Path:
    """Write a report to disk.

    The report is always written as the last report; with ``history`` it is
    also copied to a timestamped file, so consecutive sweeps can be compared.

    args:
        report (EvaluationReport): the report to persist.
        history (bool, default True): whether to keep a timestamped copy.

    returns:
        Path: the path of the last report.
    """
    payload = report.model_dump_json(indent=2)
    path = get_eval_dir() / LAST_REPORT_NAME
    _write(path, payload)
    if history:
        _write(get_history_dir() / f"{_timestamp()}.json", payload)
    return path


def load_report(filename: str = LAST_REPORT_NAME) -> EvaluationReport | None:
    """Load a report from disk.

    args:
        filename (str, default ``last_evaluation.json``): the file name to
            read, relative to the report directory.

    returns:
        EvaluationReport | None: the report, or None when nothing can be read
        (missing store, missing file or unparsable content).
    """
    try:
        path = get_eval_dir() / filename
        if not path.exists():
            return None
        return EvaluationReport.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_reports() -> list[Path]:
    """Return the saved history reports, newest first.

    args:
        (none)

    returns:
        list[Path]: the history files, most recent first.
    """
    history = get_history_dir()
    if not history.exists():
        return []
    return sorted(history.glob("*.json"), key=lambda path: path.name, reverse=True)
