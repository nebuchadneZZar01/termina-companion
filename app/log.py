"""Central logging configuration.

Every log line carries date and time. Call ``configure_logging()`` from the
entry points (``main.py`` and ``app/__main__.py``); ``LOG_LEVEL`` env var
(default ``INFO``) controls verbosity.

``INFO`` shows every first-party log, including the planning prompts
(system/user) and the raw assistant answer, each bounded by
``app.trace.LLM_LOG_PAYLOAD_LIMIT``. ``DEBUG`` additionally opens third-party
noise: Streamlit's file watcher (``watchdog``/``inotify`` events), LangChain
and the MCP server.
"""

from __future__ import annotations

import logging

from app.settings import get_settings

_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

#: Third-party loggers muted unless running at DEBUG. Streamlit's file
#: watcher logs every filesystem event at DEBUG; without this a single
#: ``streamlit run`` at INFO floods the console with inotify noise while the
#: planning prompts scroll by. At DEBUG they inherit the root level, so the
#: caller asking for everything gets everything. Only third-party watchers
#: are touched, never ``app.*``.
_NOISY_LOGGERS = ("watchdog",)


def configure_logging() -> None:
    """Configure the root logger with date, level and name.

    Three independent problems are solved here, none of which
    ``logging.basicConfig`` can handle on its own:

    1. **Handler/format.** Importing the app pulls in the MCP server, which
       calls ``basicConfig(format="%(message)s")`` at import time. Since
       ``basicConfig`` is a no-op once the root logger has a handler, relying on
       it would leave that bare formatter in place and every line would lose
       date, level and logger name. Pre-existing root handlers are therefore
       removed and replaced.
    2. **Level.** ``Streamlit`` sets the root level before us; setting it last
       makes ``LOG_LEVEL`` authoritative regardless of import order.
    3. **Noise.** Chatty third-party watchers are muted so an ``INFO`` run
       shows the planning prompts instead of inotify events; at ``DEBUG``
       they inherit the root level, since that level asks for everything.

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
    level = get_settings().log_level
    root.setLevel(level)
    # At DEBUG the caller asked for everything, so the noisy watchers are
    # reset to NOTSET (inheriting DEBUG); above it they are muted.
    noisy_level = logging.DEBUG if level == "DEBUG" else logging.WARNING
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(noisy_level)
