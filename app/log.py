"""Central logging configuration.

Every log line carries date and time. Call ``configure_logging()`` from the
entry points (``main.py`` and ``app/__main__.py``); ``LOG_LEVEL`` env var
(default ``INFO``) controls verbosity.
"""

from __future__ import annotations

import logging
import os

_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def configure_logging() -> None:
    """Configure the root logger with date, level, and name.

    args:
        (none)

    returns:
        None: side-effect on the root logger only.
    """
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format=_FORMAT,
        datefmt=_DATEFMT,
    )
