# Termina Companion

Multi-agent temporal planner for *The Legend of Zelda: Majora's Mask*, built with
LangGraph, Pydantic and Streamlit. It turns player state and a goal into a
structured, validated plan within the three-day cycle.

This is a working **end-to-end prototype**. State, Knowledge and Critic agents
use deterministic logic and structured demo data; the Planning Agent always
calls a configured LLM. The Knowledge Agent adds supplemental evidence from an
adaptive Zelda Wiki RAG cache, while MCP tools remain authoritative for game
rules. Provider configuration is required; local providers such as Ollama can
run without an external API key. In-memory player memory (preferences plus
past episodes) is active; persistent memory, tracing and full plan
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
press **Generate plan**. The UI shows retrieved knowledge, RAG status, the
indexed-page manifest, retrieved evidence provenance, plan steps and validation
outcome. While the agents run, **Generate plan** is disabled and **Stop** can
request cooperative cancellation after the current agent or LLM call. The
progress stepper is not on a timer: it repaints only when an agent finishes, so
the page stays still while the agents reason.

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

## Observability (tracing)

Every planning run gets a `run_id` and emits OpenTelemetry spans: the pipeline
root, each agent node, every LLM call, MCP tool call, RAG retrieval and the
critic's validation. By default the tracer is a **no-op** — no connection is
opened, so tests, the demo and CI run offline. To export spans to a local
[Arize Phoenix](https://phoenix.arize.com/) backend:

```sh
docker compose up -d                 # starts Phoenix (UI + OTLP/HTTP on :6006)
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:6006
uv run streamlit run main.py         # or: uv run python -m app
```

Then open http://localhost:6006 to browse each run's full trace, including the
complete system/user/assistant prompts of every LLM call (with model, token
usage and latency). Full prompts also go to console logs, but only at
`LOG_LEVEL=DEBUG` and with a bounded length. In the app, the Trace tab shows the
`run_id`, the node timeline and any errors — errors only, no prompt bodies.

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
by the second Qdrant query are formatted into planner context. A cache miss
also returns a provenance-only manifest of every page successfully indexed;
pages without a passing evidence chunk remain visible in the UI even when the
status is `wiki_miss`. On a warm hit, the manifest is derived from the source
metadata represented by returned evidence. A fresh cache hit repeats no wiki
request, so an already populated index works offline.

Retrieved evidence is diversified: at most `RAG_MAX_CHUNKS_PER_SOURCE` chunks
are kept per page and near-duplicate chunks from overlapping windows collapse
to their best-scoring representative, so one page cannot crowd out the rest. A
cache hit older than `RAG_CACHE_TTL_SECONDS` triggers one batched revision
check; only pages the wiki actually changed are refetched and reindexed, and if
that check fails the cached evidence is still served with a warning instead of
degrading to `unavailable`. `RAG_WIKI_BUDGET_SECONDS` caps the total wall-clock
time the wiki leg of a miss may consume. License discovery is best-effort: a
wiki that hides `siteinfo` yields pages without license metadata rather than
failing the retrieval.

`status` describes the outcome; `wiki_unreachable` describes source health.
Planning always continues on structured MCP context.

| Wiki leg outcome | `status` | `wiki_unreachable` | What it means |
|---|---|---|---|
| Cache hit with sufficient evidence | `cache_hit` | `false` | Served from local Qdrant, no wiki request. |
| Miss, pages indexed and evidence found | `wiki_ingested` | `false` | Wiki fetched, chunks passed second vector query. |
| Miss, reachable wiki, no useful page | `wiki_miss` | `false` | API error or nothing above threshold; plain miss. |
| Miss, wiki not reached | `wiki_miss` | `true` | Network/timeout/budget/breaker; planner uses structured MCP context only. |
| Index or embedding broken | `unavailable` | `false` | Local Qdrant/embedding failure; only case that is not a miss. |

A reachable wiki that returns an API error or no useful page is a plain miss,
not an unreachable source. Slow read/write/pool timeouts
fail fast instead of being retried, while connect errors and 429/5xx responses
keep their bounded retries. After `RAG_WIKI_FAILURE_THRESHOLD` consecutive
unreachable failures the client opens a circuit breaker and skips the wiki leg
for `RAG_WIKI_COOLDOWN_SECONDS`, so repeated planning runs do not repay the same
timeout; once the cooldown elapses one half-open request probes the wiki again.

### Configuration

Copy `.env.example` to `.env` or export these variables:

| Variable | Default | Purpose |
|---|---|---|
| `RAG_QDRANT_PATH` | `.cache/termina-companion/qdrant` | Embedded Qdrant data directory; created automatically. |
| `RAG_EMBEDDING_MODEL` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Local multilingual FastEmbed model, 384 dimensions. |
| `RAG_SIMILARITY_THRESHOLD` | `0.60` | Provisional minimum cosine score for a sufficient hit. |
| `RAG_TOP_K` | `4` | Evidence chunks returned per retrieval. |
| `RAG_MAX_PAGES_PER_MISS` | `3` | Maximum pages fetched and indexed on one miss. |
| `RAG_MAX_CHUNKS_PER_SOURCE` | `2` | Maximum evidence chunks kept per wiki page (diversity cap). |
| `RAG_REQUEST_TIMEOUT_SECONDS` | `20` | Timeout for each MediaWiki request. |
| `RAG_WIKI_BUDGET_SECONDS` | `60` | Overall wall-clock budget for the wiki leg of one miss; `0` disables it. |
| `RAG_WIKI_FAILURE_THRESHOLD` | `3` | Consecutive unreachable wiki failures that open the circuit breaker; `0` disables it. |
| `RAG_WIKI_COOLDOWN_SECONDS` | `60` | Seconds the breaker stays open before one half-open wiki probe. |
| `RAG_CACHE_TTL_SECONDS` | `604800` | Age after which cached pages are revalidated against the wiki; `0` never expires. |

The wiki API URL, request user agent and license discovery are internal to
`app/rag/wiki.py`; they are not duplicated in environment configuration.
MediaWiki `siteinfo` supplies the expected GFDL-1.3 license metadata at runtime.
Each chunk stores page ID, exact revision ID/timestamp, canonical and `oldid`
URLs, retrieval timestamp and license information. Wiki revisions replace older
chunks for the same page.

The first model-backed query may download the FastEmbed model. After the model
and wiki pages are cached, `cache_hit` retrieval does not require network
access. A wiki failure on the miss leg (network, timeout or exhausted budget)
degrades to `wiki_miss` with a warning and `wiki_unreachable=True`, because the
local index and the structured MCP context are still usable; only a Qdrant or
embedding failure returns status `unavailable`. Either way planning continues
with structured MCP context, and the planner note names the unreachable wiki
explicitly.

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

#### Threshold calibration (one-off, maintainers)

`RAG_SIMILARITY_THRESHOLD` (default `0.60`) is provisional. It was picked
with a live scenario set in `app/rag/scenarios.py`: 14 real Knowledge Agent
queries (1-2 per quest in `mock_knowledge.py`) with expected Zelda Wiki titles.
Page IDs were resolved once live and frozen for stability.

Recalibrate only when the embedding model changes, wiki titles shift, or
query logs show systematic misses. Fresh clones need nothing: the calibrated
default ships in code and `.env.example`, cache rebuilds itself on first miss.

```sh
uv run python scripts/calibrate_rag.py --thresholds 0.60 0.72 0.80 --top-k 4 8
```

The script uses an empty temp Qdrant dir (never touches `.cache/`), runs the
grid against the live wiki, prints `hit_rate` per combo to stdout and writes
no files. Example output:

```
0.60 top_k=4 -> 7/14 = 0.50 <- best
0.72 top_k=4 -> 3/14 = 0.21
0.80 top_k=4 -> 1/14 = 0.07
```

A `wiki_unreachable` combo means the wiki leg failed (timeout/budget/breaker):
planning still works on MCP data, rerun later. Only Qdrant/embedding failures
count as `unavailable`. Last calibration is recorded as
`CALIBRATED_THRESHOLD/HIT/DATE` in `app/rag/scenarios.py` and as a comment on
`RAGSettings.similarity_threshold`; override at runtime via env without code
changes.

Retrieval quality evaluation is separate from full plan/trajectory evaluation,
which remains Phase 11.

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
| `app/state.py` | `PlanningState`, including RAG evidence, status, warning, ingested pages and indexed-source manifest. |
| `app/graph.py` | LangGraph wiring and `MAX_PLANNING_ATTEMPTS = 3` loop. |
| `app/ui.py` | Streamlit frontend and provenance display. |
| `app/trace.py` | OpenTelemetry tracing seam: run spans, LLM prompt capture and the no-op/OTLP setup. |
| `docker-compose.yml` | Local Arize Phoenix observability container. |
| `app/__main__.py` | Headless pipeline demo. |
| `tests/` | Domain, validation, graph, RAG persistence, tracing and integration tests. |

Mock data spans Clock Town, Southern Swamp, Mountain Village, Great Bay, Ikana
Canyon and Romani Ranch, but is deliberately not lore-complete. The
architecture is not tied to one quest.

## Extension points

- **RAG** — tune the provisional threshold, expand wiki search scenarios and
  evaluate multilingual retrieval. Keep Qdrant/wiki access behind the Knowledge
  Agent; never expose RAG as an MCP authority.
- **Persistent memory** — in-memory preferences and episodes exist via
  `MemoryStore`; persist them (extend `GameState`, attach a graph
  checkpointer or a file/DB store behind the same protocol).
- **Tracing and audit** — add request IDs and LangGraph/tool/retrieval events.
- **Plan evaluation** — implement the Phase 11 scenario/trajectory evaluator;
  keep it separate from RAG retrieval evaluation.
