# Termina Companion

Multi-agent temporal planner for *The Legend of Zelda: Majora's Mask*, built
with LangGraph + Pydantic + Streamlit. It turns a player state and a goal into
a structured, validated plan within the three-day cycle.

This is a working **end-to-end prototype**: agents run on deterministic mock
logic and mock knowledge, so nothing needs API keys. The architecture leaves
clean extension points for real LLMs, RAG, persistent memory, tracing and
evaluation.

## Install

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync
```

## Run the Streamlit UI

```sh
uv run streamlit run main.py
```

Edit the player state (day/hour, location, inventory, completed quests), set
a goal and press **Generate plan**. The app shows the retrieved knowledge, the
plan steps and the validation outcome.

## Run the headless demo (no UI, no API keys)

```sh
uv run python -m app
```

Runs the full pipeline and prints: understood state, retrieved knowledge,
the generated plan and its validation.

## Tests

```sh
uv run pytest
```

## Linting

```sh
uv run ruff check .
uv run ruff format .
```

## Architecture

```
Game State → State Agent → Knowledge Agent → Planning Agent
          → Critic/Validator → Plan   (bounded re-planning loop on failure)
```

| Component | Responsibility |
|---|---|
| `app/domain.py` | Pydantic contracts: `GameState`, `Goal`, `Plan`, `ValidationResult`, clock/window types |
| `app/data/mock_knowledge.py` | Game data separated from logic; `KnowledgeBase.retrieve()` is the RAG seam |
| `app/agents/` | One node per agent; mock brains, clearly separated responsibilities |
| `app/state.py` | `PlanningState` — the LangGraph workflow state (Pydantic model) |
| `app/graph.py` | LangGraph wiring + bounded re-planning attempts |
| `app/ui.py` | Streamlit frontend logic |
| `app/__main__.py` | Headless pipeline demo |
| `main.py` | UI entry point (`streamlit run main.py`) |
| `tests/` | Domain model, validation and re-planning tests |

Mock data is a deliberately small vertical slice (Anju & Kafei plus a second
generic quest); the domain model and agents are not tied to a single quest.

## Extension points

- **Real LLMs** — swap the mock logic inside `app/agents/*` for model calls.
- **RAG** — replace `KnowledgeBase.retrieve`.
- **Persistent memory** — extend `GameState`; attach a checkpointer to the graph.
- **Tracing / evaluation** — LangGraph stream events / invoke hooks.