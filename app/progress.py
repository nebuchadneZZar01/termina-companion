"""Agent progress seam: emit custom LangGraph stream events.

Nodes call :func:`report` to publish point-in-time progress. When the graph is
streamed with ``stream_mode="custom"`` the UI consumes those events live; under
``invoke`` (headless demo, tests) or when the writer is unavailable the call is
a silent no-op, so agents never depend on a streaming consumer.
"""

from __future__ import annotations

from langgraph.config import get_stream_writer


def report(payload: dict) -> None:
    """Emit one custom progress event, if a stream writer is available.

    args:
        payload (dict): event body, e.g. ``{"node": "knowledge", "phase": "wiki"}``.

    returns:
        None: best-effort; never raises when no stream is active.
    """
    try:
        get_stream_writer()(payload)
    except Exception:  # noqa: BLE001 - streaming is optional, never fail a run
        return
