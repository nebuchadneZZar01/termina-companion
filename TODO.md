# Termina Companion — TODO

## Current Status

**Current phase:** Phase 11 — Evaluation

**Current milestone:** Build a minimal, runnable end-to-end prototype. ✅ Done

Status map:
* Phase 0 — Foundation: complete.
* Phase 1 — Domain Model: complete.
* Phase 2 — Multi-Agent Core: complete.
* Phase 3 — Game Knowledge: complete (multi-area data: Clock Town,
  Southern Swamp, Mountain Village, Great Bay, Ikana Canyon, Romani Ranch;
  NPCs with schedules, timed events, mask & item requirements; the Critic
  also validates required masks in addition to NPC availability).
* Phase 4 — Streamlit UI: complete.
* Phase 5 — LLM Integration: complete (6 providers; the Planning Agent
  always uses the LLM with structured output and fails explicitly when
  configuration, invocation or output is unusable; State, Knowledge and Critic
  stay rule-based and deterministic; local providers support demo mode without
  external API keys).
* Phase 6 — MCP: complete (MCP tools replace KB.retrieve(); the Knowledge
  Agent calls them in-process; the MCPServer exposes the same tools for
  external MCP clients; 6 tools: search_quests, get_npc_schedule,
  get_quest_info, get_event, get_location, check_prerequisites; in-process
  Client integration test passes).
* Phase 7 — RAG: complete (adaptive Zelda Wiki cache-aside retrieval,
  persistent embedded Qdrant, FastEmbed multilingual vectors, revision-aware
  provenance, offline warm-cache behavior and Knowledge Agent integration
  implemented; retrieval quality calibrated 2026-10-10 on 14 live scenarios:
  0.60 hits 7/14 vs 0.72 3/14 vs 0.80 1/14 at top_k=4, default now 0.60).
* Phase 8 — Memory: complete (in-memory preferences + episodic store,
  `memory` retrieve node before `state`, `memory_store` after `critic`,
  planner context only, one episode per finished run).
* Phase 9 — Guardrails & Reliability: complete (the Knowledge Agent degrades
  gracefully when MCP tools fail, malformed payloads are skipped and the
  headless/UI paths continue on structured context).
* Phase 10 — Tracing & Audit: complete (OpenTelemetry run/agent/LLM/RAG/MCP
  spans exported to a local Phoenix container via OTLP when configured, a
  cheap no-op otherwise; full LLM prompts go to spans, the Trace tab shows a
  run header, node timeline and errors only).
* Phase 11 — Evaluation: complete (9 evaluation scenarios spanning every game
  area, a deterministic evaluator with six checks — plan shape, objective
  achievement, temporal ordering, prerequisites, tool usage, critic — an
  explicit PASS/FAIL per scenario, an aggregate pass rate, a CLI harness
  (`scripts/evaluate_plans.py`) and an Evaluation tab in the Streamlit UI).
* Phase 12 — Production Readiness: not started yet.
* Phase 13 — Deployment: not started yet.

### Target flow

```text
Game State
    ↓
State Agent
    ↓
Knowledge Agent
    ↓
Planning Agent
    ↓
Critic / Validator
    ↓
PASS → Plan
FAIL → Replanning
```

The first version should run locally with a configured LLM and mock/demo data.
Local providers such as Ollama can run without an external API key.

---

# Phase 0 — Foundation

* [x] Create project structure
* [x] Configure Python environment and dependencies
* [x] Configure `pyproject.toml`
* [x] Configure pytest
* [x] Create basic README
* [x] Create demo/mock mode
* [x] Verify the project runs locally

# Phase 1 — Domain Model

* [x] Create `GameState`
* [x] Create generic game knowledge models
* [x] Create `PlanStep`
* [x] Create `GamePlan` (implemented as `Plan`)
* [x] Create `ValidationResult`
* [x] Separate game knowledge from player state
* [x] Add domain model tests

# Phase 2 — Multi-Agent Core

* [x] Implement State Agent
* [x] Implement Knowledge Agent
* [x] Implement Planning Agent
* [x] Implement Critic/Validator Agent
* [x] Define LangGraph shared state
* [x] Connect agents through LangGraph
* [x] Implement PASS path
* [x] Implement FAIL → Replanning path
* [x] Add replanning limit
* [x] Add end-to-end workflow tests

# Phase 3 — Game Knowledge

Start with a small vertical slice.

* [x] Create mock game dataset
* [x] Add Clock Town
* [x] Add a small set of NPCs
* [x] Add NPC schedules
* [x] Add relevant events
* [x] Add prerequisites
* [x] Add Anju & Kafei as an example
* [x] Keep the data model generic for future quests/content
* [x] Add tests for game knowledge queries

# Phase 4 — Streamlit UI

* [x] Create Game State editor
* [x] Day / Time
* [x] Location
* [x] Masks
* [x] Inventory
* [x] Quest progress
* [x] Goal input
* [x] Add planning action
* [x] Display generated plan
* [x] Display validation status
* [x] Display validation errors
* [x] Display replanning status
* [x] Keep technical agent trace secondary to the player experience
* [x] Disable planning action during execution and add cooperative Stop control

Primary UI flow:

```text
Game State → Goal → Plan → Validation
```

# Phase 5 — LLM Integration

* [x] Create LLM provider abstraction
* [x] Support multiple LLM providers
* [x] Configure providers through environment variables
* [x] Integrate real LLM calls
* [x] Use structured Pydantic output
* [x] Remove planner rule-based fallback; fail on missing, failed or empty LLM output
* [x] Keep Knowledge retrieval deterministic (keyword matcher; MCP tool seam)
* [x] Support local demo mode without external API keys (Ollama/LM Studio)
* [x] Add tests for LLM-dependent components where practical
* [x] Ground LLM plans against the knowledge base (refs, titles, locations,
  required items) and dedupe steps

# Phase 6 — MCP

* [x] Define game tool interfaces
* [x] Create Termina MCP server
* [x] Implement `get_npc_schedule`
* [x] Implement `get_quest_info`
* [x] Implement `get_event`
* [x] Implement `get_location`
* [x] Implement `check_prerequisites`
* [x] Integrate MCP with Knowledge Agent
* [x] Add MCP tool tests

# Phase 7 — RAG

Phase 7 now uses one adaptive, on-demand Zelda Wiki RAG source. The static
curated corpus is removed. RAG is always enabled; runtime failures degrade to
structured context rather than disabling retrieval.

* [x] Identify narrative knowledge appropriate for supplemental RAG
* [x] Remove the nine curated Clock Town documents from RAG indexing
* [x] Implement MediaWiki search and bounded page fetching
* [x] Clean parsed wiki HTML into provenance-preserving Markdown
* [x] Implement deterministic heading-aware chunking
* [x] Add FastEmbed multilingual semantic embeddings with a test adapter
* [x] Add persistent embedded Qdrant storage and model-aware collections
* [x] Implement cache-first retrieval with wiki ingestion and a mandatory second
  vector query
* [x] Add semantic sufficiency checks and ingestion locking
* [x] Preserve page/revision/license/retrieval metadata
* [x] Integrate retrieval status and evidence with Knowledge Agent state, UI
  and headless output
* [x] Test cold, warm/offline, revision-update, bounded-ingestion and
  MCP-degradation behavior
* [x] Add retrieval-only evaluation contracts and offline metrics coverage
* [x] Expose indexed wiki source manifest separately from retrieved evidence
* [x] Diversify evidence with a per-source cap and near-duplicate collapse
* [x] Revalidate stale cached pages and bound the wiki request budget
* [x] Keep license discovery best-effort so page text is never blocked
* [x] Calibrate retrieval quality on a larger live scenario set
* [x] Compare retrieval configurations and document the provisional threshold

Structured game constraints such as schedules and prerequisites remain in MCP
data/tools. RAG is supplemental narrative evidence and must not create or
override objectives. Runtime failure records `unavailable`, logs a warning and
continues with structured MCP context. Full plan/trajectory evaluation is
implemented in Phase 11.

# Phase 8 — Memory

* [x] Define `MemoryStore` interface
* [x] Add player preferences
* [x] Add episodic memory
* [x] Store previous planning attempts
* [x] Retrieve relevant previous episodes
* [x] Integrate memory into LangGraph
* [x] Start with in-memory implementation
* [x] Prepare persistent storage extension

# Phase 9 — Guardrails & Reliability

* [x] Validate structured plan output
* [x] Validate prerequisites
* [x] Validate inventory requirements
* [x] Validate temporal ordering
* [x] Validate NPC availability
* [x] Validate deadlines
* [x] Return explicit PASS/FAIL
* [x] Trigger replanning on FAIL
* [x] Handle tool failures
* [x] Prevent infinite replanning loops
* [x] Add reliability tests

# Phase 10 — Tracing & Audit

* [x] Define run/request identifier
* [x] Trace user request
* [x] Trace agent execution
* [x] Trace LLM calls
* [x] Trace retrieval
* [x] Trace tool/MCP calls
* [x] Trace validation
* [x] Trace replanning
* [x] Trace final response
* [x] Expose useful trace information in the UI

Tracing uses OpenTelemetry. Spans (pipeline, agents, LLM, RAG, MCP,
validation) are exported to a local Arize Phoenix container over OTLP/HTTP
when `OTEL_EXPORTER_OTLP_ENDPOINT` is set; without it the tracer is a no-op,
so tests, the demo and CI never need a backend. Full LLM prompts go to spans
(visible in Phoenix) and to console logs at `INFO`, bounded in length by
`LLM_LOG_PAYLOAD_LIMIT`. The
Trace tab shows the run id, a node timeline and errors only. Structured
monitoring is served by these spans plus the existing text logs.

# Phase 11 — Evaluation

* [x] Define evaluation scenarios
* [x] Start with a small scenario set (9 scenarios, one per quest, all areas)
* [x] Define expected constraints for each scenario
* [x] Implement plan/trajectory evaluator
* [x] Check tool usage
* [x] Check temporal ordering
* [x] Check prerequisites
* [x] Check objective achievement
* [x] Produce explicit PASS/FAIL
* [x] Calculate aggregate pass rate
* [x] Add regression scenarios
* [ ] Revisit `RAG_SIMILARITY_THRESHOLD` if plan pass rate degrades from RAG noise/misses
* [x] Evaluate RAG separately if RAG is implemented (retrieval-only harness)

The evaluator reads game knowledge only through the MCP tools, never the
knowledge base directly, so it measures what the Knowledge Agent could have
known. Each scenario declares goal-level expectations only; the tool
expectations are derived from the objectives the goal retrieves. The same
sweep runs from the CLI (`scripts/evaluate_plans.py`) and from the Evaluation
tab of the Streamlit UI.

Caveat: the Planning Agent rebuilds the objective chain deterministically
(`_reconcile_plan`), so the pass rate mainly measures retrieval, the chain
reconciliation and the critic — the LLM influences the step windows, not the
step set. The threshold revisit stays open until a live sweep shows a
degradation caused by RAG noise.

# Phase 12 — Production Readiness

* [ ] Complete README
* [x] Add `.env.example`
* [ ] Improve error handling
* [x] Improve logging
* [ ] Complete test suite
* [ ] Verify installation from a clean environment
* [ ] Verify end-to-end execution
* [ ] Document architecture
* [ ] Add architecture diagram
* [ ] Stabilize demo mode
* [ ] Review dependencies
* [x] Update `AGENTS.md`
* [ ] Final project cleanup

# Phase 13 — Deployment

Approach: GitHub Actions CI, container build for local use, lite monitoring
(healthcheck + the OpenTelemetry spans from Phase 10; no external services
for now).

* [ ] Add `Dockerfile` for the Streamlit app
* [ ] Add `docker-compose.yml` for local orchestration
* [ ] Run the app as a non-root user in the container
* [ ] Add healthcheck for the running app
* [ ] Add GitHub Actions workflow: run `uv sync`, `ruff check`, `pytest` on every push
* [ ] Build and tag the container image in CI
* [ ] Publish the image to a container registry (optional)
* [ ] Add deployment documentation to `README.md`
* [ ] Alerting on failed healthchecks / app errors
* [ ] Verify deployment on a clean environment

---

## Development Rules

* Complete phases incrementally.
* Keep the application runnable throughout development.
* Do not implement future phases prematurely.
* Do not model the entire game before the architecture is validated.
* Prefer working vertical slices over large amounts of incomplete data.
* When a task changes the architecture significantly, update `AGENTS.md`.
* When a task changes project progress, update this file.
* Treat the actual code as the source of truth.
