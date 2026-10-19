"""Streamlit UI entry point.

Always launches the UI: ``uv run streamlit run main.py``.
The headless pipeline demo lives in ``app/__main__.py`` (``uv run python -m app``).
"""

from app.log import configure_logging
from app.trace import setup_tracing
from app.ui import render

if __name__ == "__main__":
    configure_logging()
    setup_tracing()
    render()
