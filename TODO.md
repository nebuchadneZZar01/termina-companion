# Termina Companion — TODO

## Current Status

**Current phase:** Phase 7 — RAG

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
  uses the LLM with structured output and a rule-based fallback; State,
  Knowledge and Critic stay rule-based and deterministic; demo mode
  preserved with no API keys).
* Phase 6 — MCP: complete (MCP tools replace KB.retrieve(); the Knowledge
  Agent calls them in-process; the MCPServer exposes the same tools for
  external MCP clients; 6 tools: search_quests, get_npc_schedule,
  get_quest_info, get_event, get_location, check_prerequisites; in-process
  Client integration test passes).
* Phases 7–12: not started yet.
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

The first version should run locally without external API keys and use mock/demo data.

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
* [x] Keep Knowledge retrieval deterministic (keyword matcher; MCP tool seam)
* [x] Preserve demo mode without API keys
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

* [ ] Identify knowledge appropriate for RAG
* [ ] Prepare textual game knowledge
* [ ] Implement document ingestion
* [ ] Implement chunking
* [ ] Add embeddings
* [ ] Add vector store
* [ ] Implement retrieval
* [ ] Integrate retrieval with Knowledge Agent
* [ ] Add source/evidence information
* [ ] Evaluate retrieval quality

Structured game constraints such as schedules and prerequisites should remain structured data/tools rather than being forced into RAG.

# Phase 8 — Memory

* [ ] Define `MemoryStore` interface
* [ ] Add player preferences
* [ ] Add episodic memory
* [ ] Store previous planning attempts
* [ ] Retrieve relevant previous episodes
* [ ] Integrate memory into LangGraph
* [ ] Start with in-memory implementation
* [ ] Prepare persistent storage extension

# Phase 9 — Guardrails & Reliability

* [ ] Validate structured plan output
* [ ] Validate prerequisites
* [ ] Validate inventory requirements
* [ ] Validate temporal ordering
* [ ] Validate NPC availability
* [ ] Validate deadlines
* [ ] Return explicit PASS/FAIL
* [ ] Trigger replanning on FAIL
* [ ] Handle tool failures
* [ ] Prevent infinite replanning loops
* [ ] Add reliability tests

# Phase 10 — Tracing & Audit

* [ ] Define run/request identifier
* [ ] Trace user request
* [ ] Trace agent execution
* [ ] Trace LLM calls
* [ ] Trace retrieval
* [ ] Trace tool/MCP calls
* [ ] Trace validation
* [ ] Trace replanning
* [ ] Trace final response
* [ ] Expose useful trace information in the UI

Use ContextTracing or the selected tracing solution once the core workflow is stable.

# Phase 11 — Evaluation

* [ ] Define evaluation scenarios
* [ ] Start with a small scenario set
* [ ] Define expected constraints for each scenario
* [ ] Implement plan/trajectory evaluator
* [ ] Check tool usage
* [ ] Check temporal ordering
* [ ] Check prerequisites
* [ ] Check objective achievement
* [ ] Produce explicit PASS/FAIL
* [ ] Calculate aggregate pass rate
* [ ] Add regression scenarios
* [ ] Evaluate RAG separately if RAG is implemented

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
(structured logs + healthcheck; no external services for now).

* [ ] Add `Dockerfile` for the Streamlit app
* [ ] Add `docker-compose.yml` for local orchestration
* [ ] Run the app as a non-root user in the container
* [ ] Add healthcheck for the running app
* [ ] Add GitHub Actions workflow: run `uv sync`, `ruff check`, `pytest` on every push
* [ ] Build and tag the container image in CI
* [ ] Publish the image to a container registry (optional)
* [ ] Add deployment documentation to `README.md`
* [ ] Monitoring: structured logs for the app
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
