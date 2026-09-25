# Termina Companion

Multi-agent temporal planner for *The Legend of Zelda: Majora's Mask*, built with
LangGraph, Pydantic and Streamlit. It turns player state and a goal into a
structured, validated plan within the three-day cycle.

This is a working **end-to-end prototype**. State, Knowledge and Critic agents
use deterministic logic and structured demo data; the Planning Agent always
calls a configured LLM. The Knowledge Agent adds supplemental evidence from an
adaptive Zelda Wiki RAG cache, while MCP tools remain authoritative for game
rules. Provider configuration is required; local providers such as Ollama can
run without an external API key. Persistent memory, tracing and full plan
evaluation remain future work.

## Install

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync
```

## Run the Streamlit UI

```sh
uv run streamlit run main.py
```

Edit day/hour, location, inventory, masks and quest progress, set a goal, then
press **Generate plan**. The UI shows retrieved knowledge, RAG status and source
provenance, the plan steps and validation outcome.

## Run the headless demo

```sh
uv run python -m app
```

The demo prints understood state, structured MCP knowledge, adaptive RAG
status/evidence, the generated plan and validation. Configure an LLM first;
Ollama or LM Studio work locally without an external API key.

## Run with an LLM

```sh
export LLM_PROVIDER=openai
export LLM_API_KEY=sk-...
uv run streamlit run main.py
```

Supported providers: `openai`, `openrouter`, `ollama`, `lmstudio`, `anthropic`,
`google`. Configure `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY` and
`LLM_BASE_URL`; `.env.example` is the complete annotated reference. Missing
configuration, invocation errors and empty model output fail explicitly. The
Planning Agent never substitutes a rule-based fallback plan.

## Adaptive Zelda Wiki RAG

RAG is supplemental and always enabled. There is no `RAG_ENABLED` switch and no
static curated corpus. Zelda Wiki is the only RAG source. Structured MCP data
(objectives, schedules, events, prerequisites, items and masks) always wins over
narrative text.

The Knowledge Agent invokes RAG immediately before the Planning Agent:

```text
goal + structured objective context
        ↓
semantic query → persistent Qdrant local store
        ↓                         │
   sufficient cache hit       cache miss
        ↓                         ↓
   cache_hit              MediaWiki search → bounded page fetch
                                  ↓
                       HTML cleanup → chunks → FastEmbed
                                  ↓
                       revision-aware Qdrant upsert
                                  ↓
                         mandatory second vector query
                                  ↓
                 wiki_ingested / wiki_miss evidence
```

Fetched HTML or Markdown never bypasses vector retrieval. Only chunks returned
by the second Qdrant query are formatted into planner context. A cache hit
repeats no wiki request, so an already populated index works offline.

### Configuration

Copy `.env.example` to `.env` or export these variables:

| Variable | Default | Purpose |
|---|---|---|
| `RAG_QDRANT_PATH` | `.cache/termina-companion/qdrant` | Embedded Qdrant data directory; created automatically. |
| `RAG_EMBEDDING_MODEL` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Local multilingual FastEmbed model, 384 dimensions. |
| `RAG_SIMILARITY_THRESHOLD` | `0.72` | Provisional minimum cosine score for a sufficient hit. |
| `RAG_TOP_K` | `4` | Evidence chunks returned per retrieval. |
| `RAG_MAX_PAGES_PER_MISS` | `3` | Maximum pages fetched and indexed on one miss. |
| `RAG_REQUEST_TIMEOUT_SECONDS` | `20` | Timeout for each MediaWiki request. |

The wiki API URL, request user agent and license discovery are internal to
`app/rag/wiki.py`; they are not duplicated in environment configuration.
MediaWiki `siteinfo` supplies the expected GFDL-1.3 license metadata at runtime.
Each chunk stores page ID, exact revision ID/timestamp, canonical and `oldid`
URLs, retrieval timestamp and license information. Wiki revisions replace older
chunks for the same page.

The first model-backed query may download the FastEmbed model. After the model
and wiki pages are cached, `cache_hit` retrieval does not require network
access. A Qdrant, embedding or wiki failure returns status `unavailable`,
records a warning and lets planning continue with structured MCP context.

### RAG tests and quality checks

Tests never contact the live wiki or download a model. They cover cold misses,
warm/offline cache hits, mandatory second retrieval, revision replacement,
provenance/license handling, bounded ingestion, embedding adapters, retrieval
metrics and MCP degradation. `app.rag.evaluation` accepts an injected
retriever and scenario list, so calibration runs can remain offline. Run:

```sh
uv run ruff check .
uv run ruff format .
uv run pytest
```

Retrieval quality evaluation is separate from full plan/trajectory evaluation,
which remains Phase 11. Adjust the similarity threshold and search scenarios as
real query logs become available.

## Architecture

```text
Game State → State Agent → Knowledge Agent → Planning Agent
          → Critic/Validator → Plan   (bounded re-planning loop on failure)
```

The LangGraph workflow has four nodes, one module per agent under
`app/agents/`. Agent responsibilities remain separate. Planning output is
post-processed deterministically: references, titles and locations are grounded
to MCP objectives, duplicate steps are removed, windows are clamped to
objective slots, and the authoritative prerequisite chain is rebuilt before
validation.

| Agent | Input | Output | Engine |
|---|---|---|---|
| **State Agent** | `GameState`, `Goal` | Canonical state and summary | Rule-based state normalization and summary. |
| **Knowledge Agent** | `GameState`, `Goal` | Objectives, schedules, events, RAG evidence and context | Rule-based MCP plus adaptive RAG; RAG failure degrades to structured context. |
| **Planning Agent** | State summary and retrieved context | `Plan` | Configured LLM with deterministic grounding and temporal post-processing. |
| **Critic Agent** | `Plan`, state, objectives and NPC data | `ValidationResult` | Rule-based feasibility checks and bounded re-planning trigger. |

| Component | Responsibility |
|---|---|
| `app/domain.py` | Pydantic game-state, goal, plan and validation contracts. |
| `app/data/mock_knowledge.py` | Structured demo data; agents access it through MCP tools only. |
| `app/mcp/` | Pure game-data tools and external MCP server; authoritative knowledge seam. |
| `app/agents/` | State, Knowledge, Planning and Critic graph nodes. |
| `app/rag/` | Adaptive wiki client, cleanup/chunking, FastEmbed adapter, Qdrant store and cache-aside retrieval. |
| `app/state.py` | `PlanningState`, including RAG evidence, status, warning and ingested pages. |
| `app/graph.py` | LangGraph wiring and `MAX_PLANNING_ATTEMPTS = 3` loop. |
| `app/ui.py` | Streamlit frontend and provenance display. |
| `app/__main__.py` | Headless pipeline demo. |
| `tests/` | Domain, validation, graph, RAG persistence and integration tests. |

Mock data spans Clock Town, Southern Swamp, Mountain Village, Great Bay, Ikana
Canyon and Romani Ranch, but is deliberately not lore-complete. The
architecture is not tied to one quest.

## Extension points

- **RAG** — tune the provisional threshold, expand wiki search scenarios and
  evaluate multilingual retrieval. Keep Qdrant/wiki access behind the Knowledge
  Agent; never expose RAG as an MCP authority.
- **Persistent memory** — extend `GameState` and attach a graph checkpointer.
- **Tracing and audit** — add request IDs and LangGraph/tool/retrieval events.
- **Plan evaluation** — implement the Phase 11 scenario/trajectory evaluator;
  keep it separate from RAG retrieval evaluation.
