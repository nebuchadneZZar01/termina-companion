# syntax=docker/dockerfile:1

# TaIA Streamlit image.
#
#   docker build -t termina-companion .
#   docker run --rm -p 8501:8501 --env-file .env termina-companion
#
# The app lives on the host only through the published port; its embedded
# Qdrant store, the saved games and the FastEmbed model cache persist in the
# /data volume (RAG_QDRANT_PATH and FASTEMBED_CACHE_PATH point there).

# --- build stage: resolve the frozen lock file into a self-contained venv ---
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependency layer first, so a source edit does not reinstall the world.
# README.md is copied because the setuptools backend reads it as package readme.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY main.py ./
COPY .streamlit ./.streamlit
RUN uv sync --frozen --no-dev --no-editable

# --- runtime stage: slim interpreter, non-root user, healthcheck ---
FROM python:3.14-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    HOME=/home/app \
    FASTEMBED_CACHE_PATH=/data/fastembed \
    RAG_QDRANT_PATH=/data/qdrant \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# libgomp1 is the OpenMP runtime the ONNX FastEmbed embeddings need; the slim
# image does not ship it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown app:app /data

WORKDIR /app
COPY --from=builder --chown=app:app /app /app

USER app
EXPOSE 8501

# Streamlit answers "ok" on /_stcore/health; urllib keeps the image free of curl.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4).read().strip() == b'ok' else 1)"

CMD ["streamlit", "run", "main.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
