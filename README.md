# Termina Companion

Multi-agent temporal planner for *The Legend of Zelda: Majora's Mask*, built
with LangGraph + Pydantic + Streamlit. It turns a player state and a goal into
a structured, validated plan within the three-day cycle.

This is a working **end-to-end prototype**: the State, Knowledge and Critic
agents run on deterministic rule-based logic and structured demo data, while
the Planning Agent always calls a configured LLM. The Knowledge Agent also
uses a local, curated RAG corpus for supplemental English/Italian passages and
source evidence; MCP tools remain authoritative for structured game rules.
Provider configuration is required; local providers such as Ollama can run
without an external API key. Persistent memory, tracing and evaluation remain
future extension points; MCP exposes the game-knowledge tools to any MCP host.

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

## Run the headless demo (configured LLM)

```sh
uv run python -m app
```

Runs the full pipeline and prints: understood state, retrieved knowledge,
the generated plan and its validation. Configure a provider first; Ollama or
LM Studio can be used locally without an external API key.

## Run with an LLM

The Planning Agent always requires an LLM provider. Configure one before
starting the UI or headless demo:

```sh
export LLM_PROVIDER=openai
export LLM_API_KEY=sk-...        # see .env.example for all providers
uv run streamlit run main.py
```

Supported providers: `openai`, `openrouter`, `ollama`, `lmstudio`,
`anthropic`, `google`. Configure via `LLM_PROVIDER`, `LLM_MODEL`,
`LLM_API_KEY`, `LLM_BASE_URL`. Copy `.env.example` for the full reference.
Missing configuration, invocation errors and empty model output are reported
explicitly; the Planning Agent never substitutes a fallback plan for them.

## Tests

```sh
uv run pytest
```

## Local RAG corpus

Phase 7 adds an internal, optional retrieval layer under `app/rag/`:

* `models.py` defines source documents, chunks and retrieved evidence.
* `loader.py` loads Markdown documents with frontmatter provenance.
* `chunking.py` creates deterministic overlapping chunks.
* `retriever.py` provides keyword retrieval, a local vector adapter and hybrid
  fallback behavior.
* `store.py` provides an in-memory vector store; no external database is used.
* `embeddings.py` provides a deterministic hashed embedding baseline and the
  adapter seam for a future semantic model.

The first curated corpus lives in `app/data/knowledge/clock_town/`: nine
original, web-researched documents covering Clock Town, Anju & Kafei, the
Stock Pot Inn, Post Office/Postman, Curiosity Shop/Laundry Pool, Madame Aroma,
the Bombers, market services and English/Italian retrieval terms. Each document
keeps source URLs, retrieval date and reuse notes. Documents are paraphrased;
they do not copy guide or wiki prose.

RAG is supplemental. `search_quests` and the other MCP tools still determine
objectives, schedules, events, prerequisites, items and masks. RAG passages
are appended to planner context with their source and are also exposed in the
Streamlit **Game sources** tab. If the corpus cannot be loaded, the Knowledge
Agent records a warning and continues with structured MCP context.

Set `RAG_ENABLED=0` to disable local retrieval while debugging. The default
`HashEmbeddingProvider` is an offline baseline, not a semantic model; replace it
through the provider seam for a quality evaluation. Retrieval currently has
small English/Italian regression scenarios in `tests/test_rag.py`; a larger
scenario evaluation remains pending.

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
clearly separated responsibility. The Planning Agent always uses the
configured **LLM**; the State, Knowledge and Critic agents are deliberately
**rule-based** so their output is always grounded in the player's state and the
game data. LLM output is then repaired deterministically before the Critic
validates it.

| Agent | Input | Output | Engine |
|---|---|---|---|
| **State Agent** | `GameState`, `Goal` | canonical `GameState`, `state_summary` | **Rule-based** — alias canonicalization + template summary, always derived from the actual player state. |
| **Knowledge Agent** | `GameState`, `Goal` | `relevant_objectives`, `retrieved_context`, `retrieved_evidence` | **Rule-based MCP + optional local RAG** — drives `search_quests` → `get_npc_schedule`/`get_event`: returns the whole quest whenever any of its objectives matches the goal (no match = none), so prerequisite chains travel together. Adds bounded narrative passages and source URLs; retrieval failure degrades to structured context only. |
| **Planning Agent** | `state_summary`, `retrieved_context` | `Plan` | **LLM** — always produces the plan as structured Pydantic output (`Plan`), feeding previous validation feedback on re-planning. LLM output is post-processed deterministically: refs/titles/locations are grounded to the knowledge objectives, duplicates removed, and each step's window is clamped inside its objective's slot (temporal output guardrail). The final plan is then rebuilt against the authoritative prerequisite chain: "obtain item" steps are pruned when the player already owns what they provide (`provides_items`/`provides_masks` on `Objective`), missing chain steps are re-inserted in order and `depends_on` recomputed. |
| **Critic Agent** | `Plan`, `GameState`, objectives, NPCs | `ValidationResult` | **Rule-based on purpose** — deterministic feasibility rules (time windows, location, NPC availability, items, prerequisites, sequence). Being deterministic makes validation unit-testable and lets it reliably drive the bounded re-planning loop. |

The re-planning loop: if the Critic returns FAIL, the Planning Agent calls the
LLM again with the validation feedback (up to
`MAX_PLANNING_ATTEMPTS = 3`; see `app/graph.py`). Deterministic grounding and
reconciliation run again before each Critic validation. The loop gives up and
keeps the last plan after the limit.

| Component | Responsibility |
|---|---|
| `app/domain.py` | Pydantic contracts: `GameState`, `Goal`, `Plan`, `ValidationResult`, clock/window types |
| `app/data/mock_knowledge.py` | Game data separated from logic; agents access it only through the MCP tools |
| `app/agents/` | One node per agent; deterministic State/Knowledge/Critic logic and an LLM-only Planning Agent with deterministic post-processing |
| `app/mcp/` | MCP tools (`tools.py`) and server (`server.py`) — the single seam between agents and game data |
| `app/llm.py` | Provider factory: returns a configured chat model or raises `LLMConfigurationError` — the LLM seam used by the Planning Agent |
| `app/rag/` | Local RAG contracts, curated-document loader, chunking, keyword/vector retrieval and source evidence |
| `app/data/knowledge/clock_town/` | Nine original, web-researched Clock Town documents with bilingual aliases and provenance; supplemental to MCP data |
| `app/state.py` | `PlanningState` — the LangGraph workflow state (Pydantic model), including retrieved evidence and retrieval status |
| `app/graph.py` | LangGraph wiring + bounded re-planning attempts |
| `app/ui.py` | Streamlit frontend logic |
| `app/__main__.py` | Headless pipeline demo |
| `main.py` | UI entry point (`streamlit run main.py`) |
| `tests/` | Domain model, validation and re-planning tests |

Mock data spans several major areas (Clock Town, Southern Swamp, Mountain
Village, Great Bay, Ikana Canyon, Romani Ranch) but is deliberately NOT
lore-complete; the domain model and agents are not tied to a single quest.

## Extension points

- **RAG** — replace `HashEmbeddingProvider` with a local or hosted semantic
  embedding provider, then evaluate keyword, vector and hybrid retrieval on a
  larger scenario set. Keep RAG behind the Knowledge Agent; do not add it to
  the MCP API or let it replace structured objective data.
- **Persistent memory** — extend `GameState`; attach a checkpointer to the graph.
- **Tracing / evaluation** — LangGraph stream events / invoke hooks.