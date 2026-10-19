"""Central logging configuration.

Every log line carries date and time. Call ``configure_logging()`` from the
entry points (``main.py`` and ``app/__main__.py``); ``LOG_LEVEL`` env var
(default ``INFO``) controls verbosity. Set ``LOG_LEVEL=DEBUG`` to see the
planning prompts (system/user) and the raw assistant answer, each bounded by
``app.trace.LLM_LOG_PAYLOAD_LIMIT``.
"""

from __future__ import annotations

import logging
import os

_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def configure_logging() -> None:
    """Configure the root logger with date, level, and name.

    Installs the handler directly instead of using ``logging.basicConfig``:
    ``basicConfig`` is a no-op when the root logger already has a handler, and
    importing the app pulls in LangChain/MCP, whose MCP server calls
    ``basicConfig(format="%(message)s")`` at import time. Relying on
    ``basicConfig`` would therefore leave that bare formatter in place and every
    line would lose date, level and logger name. Replacing any pre-existing
    root handler guarantees the timestamped format actually applies.

    args:
        (none)

    returns:
        None: side-effect on the root logger only.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))
    root.addHandler(handler)
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
