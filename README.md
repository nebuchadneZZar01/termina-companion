# Termina Companion

Multi-agent temporal planner for *The Legend of Zelda: Majora's Mask*, built
with LangGraph + Pydantic + Streamlit. It turns a player state and a goal into
a structured, validated plan within the three-day cycle.

This is a working **end-to-end prototype**: the State, Knowledge and Critic
agents run on deterministic rule-based logic and mock knowledge when no
credentials are set, so the demo needs no API keys. With `LLM_API_KEY` (and
friends, see [`.env.example`](.env.example)) the Planning Agent switches to real
LLM calls. The architecture leaves clean extension points for MCP, RAG,
persistent memory, tracing and evaluation.

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

## Run with a real LLM

By default `LLM_PROVIDER` is `rule-based` and the whole pipeline runs on
deterministic brains. To enable real LLM calls for the Planning Agent:

```sh
export LLM_PROVIDER=openai
export LLM_API_KEY=sk-...        # see .env.example for all providers
uv run streamlit run main.py
```

Supported providers: `openai`, `openrouter`, `ollama`, `lmstudio`,
`anthropic`, `google`. Configure via `LLM_PROVIDER`, `LLM_MODEL`,
`LLM_API_KEY`, `LLM_BASE_URL`. Copy `.env.example` for the full reference.
Without credentials — or on any LLM error — the Planning Agent silently falls
back to its rule-based brain, so the demo always runs.

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

The system is a **LangGraph workflow of four agents**. Each agent is a graph
node exposing `run(state) -> dict` (one module under `app/agents/`) with a
clearly separated responsibility. The Planning Agent is **LLM-backed** when a
provider is configured; the State, Knowledge and Critic agents are deliberately
**rule-based** so their output is always grounded in the player's state and the
game data. When no credentials are set, the Planning Agent falls back to its
deterministic rule-based brain, keeping the demo runnable with no API keys.

| Agent | Input | Output | Engine |
|---|---|---|---|
| **State Agent** | `GameState`, `Goal` | canonical `GameState`, `state_summary` | **Rule-based** — alias canonicalization + template summary, always derived from the actual player state. |
| **Knowledge Agent** | `GameState`, `Goal` | `relevant_objectives`, `retrieved_context` | **Rule-based** — keyword matcher on `KnowledgeBase.retrieve()`, returning only objectives that match the goal (no match = none). The RAG/MCP seam. |
| **Planning Agent** | `state_summary`, `retrieved_context` | `Plan` | **LLM** — produces the plan as structured Pydantic output (`Plan`), feeding previous validation feedback on re-planning. Fallback: deterministic window-slotting that exercises the re-planning loop. |
| **Critic Agent** | `Plan`, `GameState`, objectives, NPCs | `ValidationResult` | **Rule-based on purpose** — deterministic feasibility rules (time windows, location, NPC availability, items, prerequisites, sequence). Being deterministic makes validation unit-testable and lets it reliably drive the bounded re-planning loop. |

The re-planning loop: if the Critic returns FAIL, the Planning Agent re-runs
(up to `MAX_PLANNING_ATTEMPTS = 3` ↩ see `app/graph.py`); the loop gives up and
keeps the last plan after the limit.

| Component | Responsibility |
|---|---|
| `app/domain.py` | Pydantic contracts: `GameState`, `Goal`, `Plan`, `ValidationResult`, clock/window types |
| `app/data/mock_knowledge.py` | Game data separated from logic; `KnowledgeBase.retrieve()` is the RAG seam |
| `app/agents/` | One node per agent; rule-based brains or LLM calls with deterministic fallbacks, clearly separated responsibilities |
| `app/llm.py` | Provider factory: returns a chat model or `None` (no credentials) — the LLM seam the Planning Agent falls back from |
| `app/state.py` | `PlanningState` — the LangGraph workflow state (Pydantic model) |
| `app/graph.py` | LangGraph wiring + bounded re-planning attempts |
| `app/ui.py` | Streamlit frontend logic |
| `app/__main__.py` | Headless pipeline demo |
| `main.py` | UI entry point (`streamlit run main.py`) |
| `tests/` | Domain model, validation and re-planning tests |

Mock data is a deliberately small vertical slice (Anju & Kafei plus a second
generic quest); the domain model and agents are not tied to a single quest.

## Extension points

- **MCP** — `KnowledgeBase.retrieve()` (called by the Knowledge Agent) is the
  seam where dedicated game tools (`get_npc_schedule`, `get_quest_info`, …)
  plug in later.
- **RAG** — replace `KnowledgeBase.retrieve`.
- **Persistent memory** — extend `GameState`; attach a checkpointer to the graph.
- **Tracing / evaluation** — LangGraph stream events / invoke hooks.