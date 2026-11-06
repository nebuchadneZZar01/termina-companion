# TaIA — TODO

## Current Status

**Current phase:** Phase 13 — Deployment (complete)

**Current milestone:** Build a minimal, runnable end-to-end prototype. ✅ Done

**Next up:** Phase 13 is complete: the multi-stage image, the Compose `app`
profile, the non-root runtime, the healthcheck, the deterministic eval gate
and the GHCR publication from CI are in place, with deployment, alerting and
container troubleshooting documented. The next work is the backlog item (a new
cycle anchored at Day 1 06:00 with cycle-bound item permanence).

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
  uses the LLM with structured output and fails explicitly when
  configuration, invocation or output is unusable, except under the
  `PLANNER=deterministic` evaluation baseline, which makes no call; State,
  Knowledge and Critic
  stay rule-based and deterministic; local providers support demo mode without
  external API keys).
* Phase 6 — MCP: complete (MCP tools replace KB.retrieve(); the Knowledge
  Agent calls them in-process; the MCPServer exposes the same tools for
  external MCP clients; 7 tools: search_quests, get_npc_schedule,
  get_quest_info, get_objective, get_event, get_location,
  check_prerequisites; in-process Client integration test passes).
* Phase 7 — RAG: complete (adaptive Zelda Wiki cache-aside retrieval,
  persistent embedded Qdrant, FastEmbed multilingual vectors, revision-aware
  provenance, offline warm-cache behavior and Knowledge Agent integration
  implemented; retrieval quality calibrated 2026-10-10 on 14 live scenarios:
  0.60 hits 7/14 vs 0.72 3/14 vs 0.80 1/14 at top_k=4, default now 0.60; a
  2026-10-21 re-calibration was discarded because wiki throttling made it
  untrustworthy, and the threshold was confirmed at plan level by an A/B
  sweep: 8/8 passes with RAG vs 7/8 without).
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
* Phase 11 — Evaluation: complete for plan and trajectory evaluation (12
  evaluation scenarios: one per quest plus a Zora-Mask-owned Mikau variant and
  a Day 3 late-clock variant that expects the unreachable outcome, spanning
  every game area, a deterministic evaluator
  with ten checks — plan shape, objective achievement, temporal ordering,
  prerequisites, tool usage, critic, outcome, agent order, re-plan bound, LLM
  proposal fidelity — an explicit PASS/FAIL per scenario, an aggregate pass
  rate, sweep
  metadata, a CLI harness (`scripts/evaluate_plans.py`), an Evaluation tab in
  the Streamlit UI and a persisted report; each run's scores are also posted
  to Phoenix as span annotations when tracing is configured). The
  sweep-to-sweep comparison is implemented in `app/evaluation/comparison.py`;
  the `RAG_SIMILARITY_THRESHOLD` revisit is resolved (0.60
  confirmed by an A/B sweep on 2026-10-21).
* Phase 12 — Production Readiness: complete (MCP seam, offline demo, failure
  matrix and 91% coverage, README architecture/troubleshooting, clean-environment
  verification, dependency review, cleanup).
* Phase 13 — Deployment: complete (multi-stage uv image with a non-root
  runtime, `/_stcore/health` healthcheck and a `/data` volume, the Compose
  `app` profile next to Phoenix, a deterministic evaluation gate before the CI
  image build, image build/smoke/publish to GHCR, and the
  deployment, alerting and container troubleshooting docs).

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
* [x] Correct the Anju & Kafei main path to the real nine-step chain, with
  Kafei's Mask and the Stockpot Inn Room Key as explicit objectives
* [x] Adopt the game-day clock: three days, each running 06:00-05:59, with
  hours after midnight represented as the end of the same game day
* [x] Add tests for game knowledge queries

# Phase 4 — Streamlit UI

* [x] Create Game State editor
* [x] Day / Time (Day 1-3 with the 06:00-05:59 game-day clock)
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
continues with structured MCP context. Full plan and trajectory evaluation is
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
* [x] Publish the Critic's verdict of every run as a `plan/validation` span
  annotation (the sweep scores as `evaluation/*`, Phase 11)

Tracing uses OpenTelemetry. Spans (pipeline, agents, LLM, RAG, MCP,
validation) are exported to a local Arize Phoenix container over OTLP/HTTP
when `OTEL_EXPORTER_OTLP_ENDPOINT` is set; without it the tracer is a no-op,
so tests, the demo and CI never need a backend. Full LLM prompts go to spans
(visible in Phoenix) and to console logs at `INFO`, bounded in length by
`LLM_LOG_PAYLOAD_LIMIT`. The
Trace tab shows the run id, a node timeline and errors only. Structured
monitoring is served by these spans plus the existing text logs. Every run's
trace also carries its Critic verdict as a `plan/validation` span annotation
(score 1/0, PASS/FAIL with the feasibility issues), and an evaluation sweep
adds the `evaluation/*` score annotations on the same traces; both are
best-effort through the shared client in `app/phoenix.py`.

# Phase 11 — Evaluation

* [x] Define evaluation scenarios
* [x] Start with a small scenario set (12 scenarios: one per quest plus a
  Zora-Mask-owned Mikau variant and a Day 3 late-clock unreachable variant,
  all areas)
* [x] Define expected constraints for each scenario
* [x] Implement the plan evaluator
* [x] Check plan shape
* [x] Check tool usage
* [x] Check temporal ordering
* [x] Check prerequisites
* [x] Check objective achievement
* [x] Check critic acceptance
* [x] Model cross-quest prerequisites as critic gates (transitive chain named
  in the issue, never expanded into the plan)
* [x] Produce explicit PASS/FAIL
* [x] Calculate aggregate pass rate
* [x] Add regression scenarios
* [x] Persist the evaluation report (UI worker auto-save, CLI, *Load last report*)
* [x] Record sweep metadata (RAG on/off, model, scenario ids, repeats)
* [x] Evaluate the trajectory (agent decisions, the replan loop and the LLM
  proposal before the deterministic chain rebuild)
* [x] Check the agent order of a run (MCP lookups and the Critic verdict)
* [x] Check the re-plan bound and flag a late acceptance
* [x] Flag an LLM proposal that missed expected objectives (warning)
* [x] Publish the scores to Phoenix as span annotations on each run's trace
  (overall PASS/FAIL score, one annotation per failed check, warnings labelled
  but unscored; best-effort, never failing a sweep)
* [x] Compare a sweep against the stored history and flag regressions
* [x] Revisit `RAG_SIMILARITY_THRESHOLD` if plan pass rate degrades from RAG noise/misses
* [x] Evaluate RAG separately if RAG is implemented (retrieval-only harness)

In a sweep, `app/evaluation/comparison.py` compares the report with the newest
compatible stored one (the same wiki flag wins; `--baseline PATH` overrides the
choice): `pass → fail` is flagged as a regression with the check that broke it,
`fail → pass` as an improvement, and a scenario present on only one side as
`new`/`missing`, so a partial sweep never reads as a quality drop. The CLI
prints the comparison and the Evaluation tab renders it under the metrics; the
exit code still follows the current sweep, since a regression is already a
failing scenario.

The evaluator reads game knowledge only through the MCP tools, never the
knowledge base directly, so it measures what the Knowledge Agent could have
known. Each scenario declares goal-level expectations only; the tool
expectations are derived from the objectives the goal retrieves. The same
sweep runs from the CLI (`scripts/evaluate_plans.py`) and from the Evaluation
tab of the Streamlit UI.

Caveat: the Planning Agent rebuilds the objective chain deterministically
(`_reconcile_plan`), so the pass rate mainly measures retrieval, the chain
reconciliation and the critic — the LLM influences the step windows, not the
step set. A kept step keeps the LLM's window only when it fits the chain
(after its dependencies, after the previous step, before the successor's
slot) and is re-slotted on a 1h slot otherwise, so the rebuilt plan is always
chronological and non-overlapping. The threshold revisit is resolved below.

Live sweep (llama3.2 on a local Ollama, 2026-10-21, before the scenario set grew
to ten quests): 8 of 9 scenarios pass in
a single attempt, `deed-chain` failed with an empty LLM plan (reported as a
run error, not as a scenario without issues). The first live sweep exposed
three defects, now fixed: the local OpenAI-compatible base URL needed its
`/v1` path (otherwise every call answers "404 page not found"), a crashed run
was reported as a scenario without issues, and the rebuilt plan kept the LLM's
whole-slot windows, so the critic rejected the first attempt with a sequence
conflict and the run needed a re-plan.

Threshold verdict (A/B sweep, llama3.2, 2026-10-21, four scenarios twice):
`rag on` passes 8/8 with healthy retrieval (`wiki_ingested` on a cold page,
`cache_hit` elsewhere), `rag off` passes 7/8, the single failure being an empty
LLM plan — the same LLM flake seen on both conditions, so it is not
RAG-caused. The pass rate does not degrade with RAG, so
`RAG_SIMILARITY_THRESHOLD` stays at the calibrated 0.60. A live threshold
re-calibration attempted the same day was deliberately discarded: the Zelda
Wiki throttles sustained request bursts (~15s per response, the circuit
breaker opening mid-grid), so later combinations measure the rate limit, not
the threshold — the monotone order 0.60 > 0.72 > 0.80 held in every run and
`CALIBRATED_*` keeps the clean 2026-10-10 measurement; calibration runs need
`RAG_WIKI_BUDGET_SECONDS` in the hundreds and still may not complete. Two
reporting defects surfaced while collecting the comparison and were fixed: a
disabled retrieval raised a pydantic validation error (every `--rag off` run
recorded `unavailable` and leaked the error text into the planner prompt), and
`--json` copies of the report missed the `created_at` stamp. Running the CLI
sweeps while the Streamlit UI is open needs an isolated store (copy the warm
`.cache/termina-companion/qdrant` and point `RAG_QDRANT_PATH` at it), because
the embedded Qdrant client holds an exclusive lock on its path.

# Validator & Planner Hardening

Follow-ups to take before Phase 12. The first two are defects in the planner
and the Critic, the third is an ablation the evaluation harness already
supports.

## Temporal reachability

Implemented. The three days are one finite timeline: a window is a dated
occurrence inside it, so once it is over everything that needed it is over too,
and only the Song of Time reopens it. An objective flagged `recurring` is the
explicit exception: a daily availability that repeats every game day with its
time of day and never falls into the past.

* [x] Stop scheduling closed windows: `_window_inside` reports "no slot" instead
  of falling back to the objective window's start, and `occurrences()` drives
  both one-off and recurring availability.
* [x] Cut the unreachable branch of the chain: `app/agents/reachability.py`
  closes the branch over `prerequisites` and over the `requires_quests` gate,
  while objectives of unrelated quests stay plannable.
* [x] Add an independent Critic check against `game_state.time` (step starts
  before now, objective window already closed), naming the quest, the objective,
  the window end and the Song of Time; an empty plan is `unreachable`, never a
  generic `empty`.
* [x] Stop re-planning when the only errors are temporal, mirroring the
  `quest_prerequisite` give-up: `_TERMINAL_KINDS` in `app/graph.py`.
* [x] Add tests: `_window_inside` on a closed window, a Day 2 chain whose Day 1
  steps are dropped, the Critic issue, the graph give-up, plus the deterministic
  clock matrix in `tests/test_temporal_matrix.py`.
* [x] Update `AGENTS.md` and `README.md`.
* [x] Track progress per objective: `GameState.completed_objectives`, the
  sidebar "Completed objectives" picker, `app/agents/progress.py` and save v3
  (version-2 files load unchanged). Progress is never inferred from location.
* [x] Flag daily availability: `Objective.recurring` with a validator that
  rejects a recurring objective bound to an event, and a golden test pinning the
  reviewed set of daily quests.
* [x] Report a chain that no longer fits, instead of trimming it: the shared
  `app/agents/scheduling.py` decides what the cycle can hold, the planner takes
  the placement from it and the Critic reports each objective it had to lose as
  `unreachable` plus any step the plan lost as `missing_step`. A valid plan can
  no longer omit a required objective.

## Critic independence

The Critic never trusts the planner's output: a grounding mistake cannot hide
a real infeasibility.

* [x] Read item and mask requirements from the `Objective`, not from the plan
  step fields the grounding produced.
* [x] Recompute dependency timing from `objective.prerequisites` and the steps
  present earlier, instead of trusting `step.depends_on`.
* [x] Resolve plan refs against the full knowledge base and treat an unknown
  ref as an error (the Critic reaches it through the `get_objective` MCP tool
  and its memoized `critic_knowledge.py` view).
* [x] Add a global overlap check between consecutive steps, not only along
  `depends_on` edges (new `overlap` issue kind).
* [x] Add tests: corrupted step requirements and dependencies are still
  rejected, an unknown ref is rejected, overlapping consecutive steps are
  flagged.

## Out-of-cycle behavior

* [x] Decided and implemented: an infeasible plan plus the Song of Time message,
  not a plan dated in the past.
* [x] Add `expected_outcome` to the evaluation scenarios, so a sweep can assert
  "unreachable at this clock" instead of only checking the plan shape. The
  deterministic clock matrix in `tests/test_temporal_matrix.py` also covers the
  case in `pytest`. Implemented as `PlanScenario.expected_outcome`
  (`plan`/`unreachable`) with an `outcome` check, a validator that rejects the
  contradictory combination, and the `anju-kafei-late` scenario pinned at Day 3
  00:00, where all nine chain objectives are closed and no LLM call happens.

## Deterministic baseline ablation

* [x] Add a planner engine switch (`PLANNER=llm|deterministic`) and a
  `--planner` flag in the evaluation CLI (also a picker in the Evaluation tab).
  The engine travels per run in `PlanningState.planner` and is never a
  process-wide mutation, so a UI sweep thread cannot leak it.
* [x] Build the baseline as `_reconcile_plan` over an empty plan, recording
  `plan_engine="deterministic"` and no `plan_proposal` (the fidelity check
  skips itself).
* [x] Record the planner engine in the sweep metadata so two saved reports stay
  comparable, and never select a baseline from the other engine.
* [x] Run an A/B sweep and document the result: pass rate, attempts and what
  the model adds beyond the deterministic chain. Run both engines with the same
  `--rag` flag on a warm store, discard a sweep whose `wiki_retrieval` is
  `degraded`, and keep `run_error` scenarios out of the engine comparison.
  Measured 2026-10-29 (`llama3.2` on Ollama, `--rag off`, one deterministic
  sweep and three LLM sweeps, no `run_error`): 12/12 deterministic and 36/36
  LLM, identical step counts on every scenario, 14 proposal-fidelity warnings
  in 36 LLM runs across 8 of the 11 plan scenarios, no re-plan on either side,
  ~34 min of model time per LLM sweep against under a second. Numbers and
  protocol live in `README.md` under *The deterministic baseline*.
* [x] Fix the two harness bugs the first sweeps surfaced and re-measure:
  `rr_defend_ranch` bound an event to Romani's daytime schedule, which no plan
  could satisfy, and the evaluator judged recurring objectives against their
  Day 1 occurrence only. Both are fixed (`fix(knowledge)`, `fix(evaluation)`),
  the data invariant is pinned by a test, and the rerun above is the
  measurement after the fixes.

# Phase 12 — Production Readiness

* [x] Complete README (install/first run, architecture, troubleshooting, offline demo)
* [x] Add `.env.example`
* [x] Improve error handling (offline CLI failures, graph node errors recorded,
  broken save directory degrades on load; failure-path matrix)
* [x] Improve logging
* [x] Complete test suite (692 tests, 91% line coverage, failure-path matrix;
  `pytest-cov` in the dev group)
* [x] Verify installation from a clean environment (fresh clone,
  `uv sync --frozen`, ruff, 692 tests, offline demo)
* [x] Verify end-to-end execution (offline demo exit 0; LLM smoke on local
  Ollama, valid 9-step plan; Streamlit health `/_stcore/health`)
* [x] Document architecture
* [x] Add architecture diagram (Mermaid in `README.md`)
* [x] Stabilize demo mode (offline `--deterministic --no-rag` run, tested)
* [x] Review dependencies (every direct runtime dependency is imported; direct
  updates are available but deferred to avoid unrelated upgrades; `uv lock
  --check` clean, `pytest-cov` dev-only)
* [x] Route the State Agent and the planner's `planning_chain.py` through the
  `app/mcp/tools.py` seam instead of importing `build_default_knowledge()`
  directly.
* [x] Update `AGENTS.md`
* [x] Final project cleanup (stale TODO notes closed, local artifacts ignored,
  final ruff/format/pytest green)

# Phase 13 — Deployment

Approach: GitHub Actions CI, container build for local use, lite monitoring
(healthcheck + the OpenTelemetry spans from Phase 10; no external services
for now).

* [x] Add `Dockerfile` for the Streamlit app (multi-stage uv build, slim
  runtime, `/data` volume)
* [x] Add `docker-compose.yml` for local orchestration (the `app` profile runs
  TaIA next to Phoenix and overrides the OTLP endpoint for the Compose network)
* [x] Run the app as a non-root user in the container (uid 10001)
* [x] Add healthcheck for the running app (`/_stcore/health`, declared both in
  the image and by Compose)
* [x] Add GitHub Actions workflow: run `uv sync`, `ruff check`, `pytest` on every push
* [x] Gate the image build on the deterministic evaluation sweep (`eval-gate`
  job: 12 scenarios, no LLM or wiki access, `--min-scenarios 12`)
* [x] Build and tag the container image in CI (`type=sha` plus `latest` on
  `main`), with an offline smoke test of the built image
* [x] Publish the image to a container registry (GHCR on `main` and `v*` tags;
  pull requests build only)
* [x] Add deployment documentation to `README.md`
* [x] Alerting on failed healthchecks / app errors (Docker healthcheck plus
  `restart: unless-stopped`; the external monitor/webhook recipe and the
  container log stream are documented in the README)
* [x] Verify deployment on a clean environment (image built from scratch, app
  healthy on `:8501`, offline demo exit 0 inside the image, Compose
  `app` profile healthy, non-root write on the `/data` volume)

# Backlog

Deferred beyond the production-readiness work; not a Phase 12 prerequisite.

* [ ] Plan the next cycle. It needs item/mask permanence in the knowledge base
  (the letter, the room key and the pendant are cycle-bound and reset with the
  Song of Time), a cycle reference on `Plan` anchored at Day 1 06:00, a Critic
  check against the shifted clock and an evaluation scenario.

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
