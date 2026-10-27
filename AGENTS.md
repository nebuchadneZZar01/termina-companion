# AGENTS.md

## Project

**Termina Companion** is a multi-agent AI companion for *The Legend of Zelda: Majora's Mask*.

The goal is to build a **temporal planning system** that helps a player decide what to do based on:

* current day and time
* location
* inventory and masks
* quest progress
* NPC schedules
* prerequisites
* temporal constraints
* player goals

This is **not** a generic Zelda chatbot.

## Technology

Use:

* Python
* LangChain
* LangGraph
* Pydantic
* Streamlit
* MCP (Model Context Protocol)

## Architecture

The system must be a **multi-agent system** orchestrated with LangGraph.

Initial agents:

* **State Agent** — understands the player's current state.
* **Knowledge Agent** — retrieves relevant game knowledge.
* **Planning Agent** — creates a structured temporal plan.
* **Critic/Validator Agent** — checks whether the plan is feasible.

If validation fails, the workflow should support re-planning.

Keep agent responsibilities clearly separated.

## Scope

The final system should support multiple quests, NPCs, events, items, locations and objectives across Majora's Mask.

The initial implementation should use a **small vertical slice**, such as Clock Town and the Anju & Kafei quest, to validate the architecture.

Do not design the core architecture around a single quest.

Keep game knowledge separate from player state and application logic.

## Initial Goal

First build a small but **working end-to-end prototype**:

```text
Game State → Goal → Multi-Agent Planning → Validation → Plan
```

The prototype should run locally and include a simple Streamlit UI.

Mock/demo data is acceptable initially.

RAG is now an adaptive, supplemental Knowledge Agent seam backed only by the
Zelda Wiki. Keep it separate from MCP and do not let textual evidence override
structured objectives, schedules, events, prerequisites, items or masks. The
Knowledge Agent searches persistent embedded Qdrant first, fetches and indexes
wiki pages on a miss, then performs a mandatory second vector retrieval. Raw
fetched text never reaches the planner directly. Warm hits are diversified
(per-source cap plus near-duplicate collapse) and revalidated against the wiki
once older than a configurable TTL; the wiki leg of a miss runs under a global
time budget and license discovery is best-effort. Slow wiki timeouts fail fast
instead of being retried, and repeated unreachable failures open a short circuit
breaker so a down wiki is not repaid on every run. A wiki failure on that leg
degrades to a `wiki_miss` with a warning and an explicit `wiki_unreachable`
flag, so a single slow request never turns retrieval `unavailable`; only an index
or embedding failure does. Either way the pipeline continues with structured
context. Persistent memory remains future work; leave clear extension points
for it. Plan evaluation is implemented in `app/evaluation/`.

## Development Principles

* Prefer simple implementations over premature abstraction.
* Keep domain models structured with Pydantic.
* Keep game data separate from agents.
* Keep the application runnable at every stage.
* Add tests for important domain and validation logic.
* Do not attempt to model the entire game initially.
* Do not use game decompilation as the initial data source.
* Follow Python standards: PEP 8, the package lives under `app/` with
  imports as `from app import ...`, the Streamlit UI entry point is `main.py`
  at the repository root, and the headless demo runs via `python -m app`.
* Follow and keep `TODO.md` coherent: check off tasks only once the code
  actually does them, and update project progress whenever a phase or
  milestone changes.

## Current Layout

* `main.py` — Streamlit UI entry point at the repository root.
* `app/domain.py` — system-wide Pydantic contracts (GameState,
  ClockTime/TimeWindow, Plan, ValidationResult). The clock follows the
  game-day model: `day` is 1-3 and `hour` is 6-29, where hours 24-29 are
  `00:00-05:59` of the night at the end of the same game day. Input hours
  0-5 are normalized to 24-29, `display_hour`/`next_morning` drive the
  `Day 1, 02:30 (+1)` rendering, and the cycle ends at Day 3 29:59.
  `GameState.completed_objectives` is the explicit list of objectives the
  player already did; progress is never inferred from the location.
* `app/data/mock_knowledge.py` — game data (areas, quests, objectives,
  NPCs, events, windows, mask/item requirements). Data covers several
  major areas but is deliberately NOT lore-complete; do not tie the
  architecture to one quest. The Anju & Kafei vertical slice is the
  game-accurate nine-step main path (Kafei's Mask, Room Key, kitchen
  letter, posting it, Kafei, pendant, Sakon's Hideout, reunion), with
  optional rewards mentioned only in descriptions. The Knowledge Agent and
  the Critic read it only through the tool functions in
  `app/mcp/tools.py`; the State Agent and the planner's `planning_chain.py`
  still call `build_default_knowledge()` directly for quest names and
  objective positions (tracked in `TODO.md`). An objective's window is a
  dated occurrence in the three-day cycle unless it is marked
  `recurring=True`: a recurring objective is a daily availability (a place to
  visit, an NPC to talk to) that repeats every game day at the same time of
  day and can never fall into the past. The marking criterion is strict — no
  `event_ref` (a validator rejects the contradiction), no single-hour scene,
  and no game day named in the title or description — and a golden test pins
  the reviewed set (Darmani, Goron Lullaby, Mikau, Pamela, Song of Storms, Deku
  Princess, title deeds); the Anju & Kafei, Bombers and Romani Ranch chains
  stay one-off.
* `app/agents/` — one module per agent (state, knowledge,
  planning, critic), each exposing a LangGraph node function `run(state) -> dict`.
  The Planning Agent's deterministic post-processing lives beside it in
  `planning_draft.py` (LLM draft schema and strict materialization),
  `planning_chain.py` (grounding, clamping and prerequisite-chain rebuild),
  `planning_clock.py` (shared cycle arithmetic, including the `occurrences`
  of an objective still open at the player's clock) and `progress.py`
  (`done_objective_ids`, the progress summary and the sidebar's objective
  labels). `reachability.py` is the pure closure that answers what the clock
  has already closed: `dead_objectives` maps each stranded objective to the
  root objective that ended its branch, `dead_quests` reports the gated quests
  that can no longer be completed, and the quest lookup is injected so the
  planner reads the knowledge base while the Critic stays behind its
  MCP-backed view.
  State, Knowledge and Critic run deterministic rule-based logic. The State
  Agent lists completed quests only and never infers an active quest from the
  player's location. The Planning
  Agent always calls the configured LLM unless every retrieved objective is
  already out of reach; missing configuration, invocation errors and empty
  output fail explicitly. LLM output is post-processed
  deterministically: refs, titles and locations are grounded to the knowledge
  objectives and each step's window is clamped inside an availability
  occurrence still open at the player's clock, never before it
  (see `app/agents/planning_agent.py`); a closed objective has no slot and its
  step is dropped. The final plan is then rebuilt against the
  authoritative objective chain: `search_quests` retrieves a whole quest when
  any of its objectives matches; objectives up to the furthest reward the
  player already owns (`provides_items`/`provides_masks` on `Objective`) are
  treated as done, so a trade chain never asks again for items traded away,
  and "obtain item" steps beyond it are pruned when their reward is owned.
  When the manually entered inventory contradicts that position (a later
  reward owned but an earlier required mask missing) the planner falls back to
  pruning only owned-provide steps, and the objectives the clock has closed
  are filtered out of both branches. Missing chain steps are re-inserted in
  prerequisite order and `depends_on` is recomputed; a kept step keeps the
  LLM's window only when it
  fits the chain — after its dependencies, after the previous step, before the
  successor's next open occurrence — and is re-slotted onto a 1h window
  otherwise, while a re-plan re-slots every window, so the rebuilt plan is
  always chronological, non-overlapping and never in the past, and the LLM's
  windows are only advisory. The Knowledge Agent ships one rendered context
  block per objective (`PlanningState.planner_context_blocks`) plus the RAG
  evidence tail, so the planner leaves the closed objectives out of the prompt
  by selecting blocks; when nothing is left it makes no LLM call and returns an
  empty plan with `plan_engine="unreachable"` and no proposal. All timing
  arithmetic uses the 06:00-29:59 game-day cycle, not a midnight rollover.
  Cross-quest prerequisites are gates, not planned steps: an objective's
  `requires_quests` (and its transitive closure) must be marked `done` in
  `quest_progress`, planned as the prerequisite quest's terminal step, or
  already owned through that step's reward. Otherwise the Critic reports a
  `quest_prerequisite` issue naming the missing chain; when that quest can no
  longer be completed it becomes an `unreachable` issue instead. The graph stops
  re-planning on either kind, since a new plan cannot complete a quest or reopen
  a window.
  The Critic never trusts the plan step fields: it resolves every ref against
  the whole knowledge base through the MCP tools, reads item and mask
  requirements from the authoritative `Objective`, recomputes dependency
  timing from `objective.prerequisites` and the earlier steps, rejects an
  unknown ref as an error and flags overlapping consecutive steps. Temporal
  reachability is checked twice: a step that starts before the player's clock,
  or whose one-off window has closed, is an `unreachable` error asking for the
  Song of Time, and one `unreachable` issue per dead chain names the quest, the
  missed objective, the window end and the Song of Time even when the plan still
  lists the feasible steps. An empty plan is `empty` only when nothing is out of
  reach. Its memoized per-validation knowledge view lives in
  `critic_knowledge.py`.
  The planner also
  returns its untouched proposal as `plan_proposal` (the input the
  `proposal_fidelity` check compares), and the Critic appends one
  `AttemptRecord` to `attempt_log` per validated attempt. The Knowledge
  Agent calls MCP tools in-process for authoritative
  structured data, then calls `app.rag.retriever.retrieve` for adaptive wiki
  evidence. Retrieval runs immediately before planning; RAG failure is logged
  and degrades to structured context, never changing the objective chain.
* `app/mcp/` — MCP tools and server. `app/mcp/tools.py` holds the pure
  tool functions (search_quests, get_npc_schedule, get_quest_info,
  get_objective, get_event, get_location, check_prerequisites) — the
  game-data seam. `app/mcp/server.py` wraps them as a `MCPServer` for
  external MCP clients. The Knowledge Agent and the Critic import them
  directly for in-process use; the State Agent and `planning_chain.py` still
  read the knowledge base directly (see `TODO.md`). RAG is not exposed as an
  MCP tool.
* `app/rag/` — adaptive supplemental RAG package: Pydantic document/chunk/
  evidence/source-manifest contracts, MediaWiki client and HTML cleanup,
  heading-aware chunking, FastEmbed adapter, persistent embedded Qdrant store,
  ingestion lock and cache-aside retrieval. `retrieve` is the Knowledge Agent
  seam; it always attempts retrieval (except when `RAG_ENABLED` turns it off,
  which returns the `disabled` status without touching any backend), records
  `cache_hit`/`wiki_ingested`/`wiki_miss`/`unavailable`/`disabled`, and fails
  soft without bypassing MCP authority. A
  wiki-leg failure maps to `wiki_miss` with a warning and a `wiki_unreachable`
  flag when the wiki could not be reached; only an index or embedding failure
  maps to `unavailable`.
  Its post-store evidence selection caps chunks per source and collapses
  near-duplicates, stale hits are revalidated through a batched revision check,
  and the wiki client enforces a global request budget with best-effort license
  metadata, fails fast on slow read timeouts, and opens a cooldown circuit
  breaker after repeated unreachable failures. Indexed-source metadata is
  exposed for UI inspection, while only retrieved evidence is appended to
  planner context. `app/rag/evaluation.py`
  provides retrieval-only offline metrics; it does not evaluate plans or
  trajectories. `app/rag/scenarios.py` holds the 14 live calibration queries
  with frozen wiki titles; `scripts/calibrate_rag.py` reruns the threshold grid
  (current provisional default `0.60`, calibrated 2026-10-10).
* `app/settings.py` — the single environment contract. `Settings`
  (Pydantic settings) declares every `LLM_*`, `LOG_LEVEL`, `OTEL_*` and
  `PHOENIX_*` variable plus the nested `RAGSettings` (`RAG_` prefix, including
  `RAG_ENABLED`); blank optional values load as `None`, `LLM_API_KEY` is a
  `SecretStr`, and derived properties expose the Phoenix annotation URL and
  the Phoenix UI URL. `get_settings()` builds a fresh instance (not cached, so
  runtime env changes such as the evaluation A/B flag are seen) and is called
  first by `configure_logging()`, so a malformed value fails at startup.
  `load_dotenv()` lives here: `.env` still populates the process environment
  once and tests stay hermetic.
* `app/llm.py` — LLM provider factory (`get_chat_model()`); raises
  `LLMConfigurationError` when no usable provider is configured. Reads
  `LLM_*` through `app/settings.py`; `default_model_for()` exposes the
  per-provider default the sidebar shows when `LLM_MODEL` is unset. Local
  OpenAI-compatible servers (Ollama, LM Studio) get their `/v1` path added
  when `LLM_BASE_URL` names only a host; `llm_error_hint()` turns a failed
  call into an actionable message (base URL, API key, server down). The
  Planning Agent has no rule-based fallback.
* `app/phoenix.py` — the shared Phoenix span-annotation client: endpoint
  resolution (`PHOENIX_BASE_URL` else the OTLP endpoint, so annotations land
  where the traces do), explanation clipping, deterministic
  `termina:{run_id}:{suffix}` upsert identifiers and a fail-soft
  `post_annotations()` that can never break a run or a sweep.
  `publish_plan_validation()` annotates every run's trace with the Critic's
  verdict (`plan/validation`, score 1/0 with PASS/FAIL and the issues in the
  explanation) and is called by `run_pipeline` once the root span is closed;
  the evaluation harness builds its `evaluation/*` payloads on top of the
  same client (`app/evaluation/phoenix.py`).
* `app/log.py` — console logging setup: `configure_logging()`, called from both
  entry points, installs one timestamped handler
  (`%(asctime)s %(levelname)s [%(name)s] %(message)s`) and reads a single
  `LOG_LEVEL` env var (default `INFO`). It replaces existing root handlers
  instead of calling `logging.basicConfig`, which is a silent no-op once the
  MCP server has installed its bare `%(message)s` handler at import, and sets
  the root level last so it wins over whatever the libraries configured.
  `INFO` shows every first-party log, including the planning system/user
  messages and the raw assistant answer; `DEBUG` additionally opens
  third-party noise (Streamlit's file watcher, LangChain, the MCP server).
  Chatty third-party watchers (`_NOISY_LOGGERS`, currently `watchdog`) are
  muted at `INFO` and reset to inherit at `DEBUG`. Message bodies are always
  bounded by `LLM_LOG_PAYLOAD_LIMIT`, so one runaway prompt cannot flood the
  console at either level.
* `app/save.py` — `SaveSnapshot` plus `save_state`/`load_state`: persists the
  sidebar form (day/time, location, masks, inventory, completed objectives,
  quest progress, goal) as JSON in `saves/last_save.json` under the save
  directory derived from `RAG_QDRANT_PATH`. The file is at version 3; version-2
  saves carry no completed objectives and load unchanged. Version-1 saves are
  migrated to the game-day clock on
  load: an old early-morning hour moves to the previous game day's night
  (`Day 2 02:00` -> `Day 1 26:00`), while an invalid pre-dawn Day 1 time
  clamps to `Day 1 06:00` and carries a `migration_warning`. Corrupt or
  missing files load as `None` (the UI warns and keeps the current state);
  the Streamlit sidebar Save/Load buttons are the only caller.
* `app/state.py` — `PlanningState`, the workflow state threaded
  through the graph (Pydantic model, used as the LangGraph state schema),
  including retrieved evidence, indexed-source manifest, retrieval status,
  player preferences, relevant past episodes, the `tool_calls` list the
  Knowledge Agent records (MCP tools as `"tool"` or `"tool:<arg>"`), plus the
  trajectory the trajectory checks read: `plan_proposal` (the LLM's plan
  before grounding and reconciliation) and `attempt_log` (one `AttemptRecord`
  per planning attempt, appended by the Critic). `planner_context_blocks` holds
  the Knowledge Agent's rendered context per objective and
  `planner_context_suffix` the RAG evidence tail, so the planner can drop the
  objectives the clock closed without editing text.
* `app/evaluation/` — plan evaluation. `models.py` holds the
  Pydantic contracts (`PlanScenario`, `EvaluationIssue`, `ScenarioResult`,
  `EvaluationReport`); a crashed run counts as one error and a `run_error`
  failure kind, never as a scenario without issues; `scenarios.py` holds the
  eleven shipped scenarios (one per quest plus a Zora-Mask-owned Mikau
  variant, spanning every game area, including the game-accurate nine-step
  Anju & Kafei chain). Scenarios that depend on a gate seed the prerequisite
  quests as `done` and use `forbidden_objective_refs` to prove those quests
  are not planned; `evaluator.py` is the deterministic
  evaluator with nine checks — plan shape, objective achievement, temporal
  ordering, prerequisites, tool usage, critic, plus the three trajectory checks
  in `trajectory.py` (agent order, re-plan bound, LLM proposal fidelity) that
  only fire on a recorded run — reading game knowledge only
  through the MCP tools, never the knowledge base directly, so it measures
  what the Knowledge Agent could have known; `runner.py` runs the scenarios
  against the live pipeline (memory store cleared before each scenario) and is
  shared by the CLI harness and the UI; `phoenix.py` builds each sweep's
  score payloads on the shared client (`app/phoenix.py`) and posts them
  to Phoenix as span annotations on the run's own trace — `evaluation/overall`
  (score 1/0 with PASS/FAIL), one annotation per failed check, warnings
  labelled but unscored — only when a Phoenix endpoint is configured
  (`PHOENIX_BASE_URL` or the OTLP endpoint), flushing pending spans first and
  failing soft, so an unreachable Phoenix never fails a sweep;
  `storage.py` persists the report in
  the save directory derived from `RAG_QDRANT_PATH` (`last_evaluation.json`
  plus a timestamped `evaluations/` copy; a missing creation date is stamped
  once before any write, so every copy of a sweep agrees), so the checks
  outlive the session:
  the UI worker writes it when a sweep finishes and *Load last report* reads
  it back. The report also carries sweep metadata (RAG flag, producing model,
  repeat count, creation timestamp) so two saved sweeps can be compared; its
  `wiki_retrieval` computed field reports what the runs actually recorded
  (`off`/`on`/`degraded`/`unknown`) instead of echoing the requested flag, so a
  sweep whose wiki leg died partway is never labelled healthy; `wiki_miss` is
  not degraded, it is also the ordinary outcome of an irrelevant query.
  `RAG_ENABLED` (`rag_enabled()` in
  `app/rag/retriever.py`) switches the supplemental wiki retrieval off for
  A/B runs. `comparison.py` compares a sweep with the newest compatible stored
  one: `select_baseline` skips the report itself and prefers the same wiki
  flag, `compare_reports` classifies every scenario as
  `regressed`/`improved`/`new`/`missing` (a pass→fail is a regression with its
  new failing checks; a scenario present on one side only is a gap, never a
  regression, so a partial sweep cannot look like a quality drop) and carries
  both sides' pass counts and metadata. `storage.load_history()` reads the
  timestamped copies newest first and skips corrupt files.
* `scripts/evaluate_plans.py` — CLI harness for the evaluation sweep:
  `--scenario`, `--repeat`, `--rag on|off`, `--baseline PATH`, `--json`,
  `--list`; prints one
  PASS/FAIL line per scenario plus the aggregate pass rate, then the comparison
  against the newest stored sweep (or `--baseline`), and exits 1 when
  any scenario fails. It always writes the shared last report (same store as
  the UI) and `--json PATH` writes an extra copy. It needs a configured LLM
  provider and is not part of pytest.
* `app/memory/` — player memory: Pydantic `PlayerPreferences`/`Episode` models
  plus the `MemoryStore` protocol with the thread-safe `InMemoryMemoryStore`
  (keyword ranking; the protocol is the extension point for future persistence).
* `app/agents/memory_agent.py` — `retrieve_run` (before `state`) and `store_run`
  (after `critic`, one episode per finished run, planner context only).
* `app/graph.py` — graph wiring and the bounded re-planning
  loop (max `MAX_PLANNING_ATTEMPTS = 3`) driven by the Critic Agent. The loop
  gives up immediately when every error issue is terminal (`_TERMINAL_KINDS`):
  a `quest_prerequisite` gate cannot be satisfied by another plan, the
  prerequisite quests are never expanded into the plan, and an `unreachable`
  window cannot be reopened without the Song of Time.
  `run_pipeline` also posts the run's Critic verdict to Phoenix as a
  `plan/validation` span annotation (best-effort, via `app/phoenix.py`).
  Each node is
  wrapped to announce its start on the custom progress stream, open one
  `node.*` trace span and record its outcome (duration, status, detail) for
  the run audit; a failing node is also added to the run's error list.
* `app/ui/` — Streamlit frontend package. `page.py` exposes `render()`, the
  only public entry point (`from app.ui import render`). `theme.py` holds the
  CSS, `formatting.py` the shared formatters/entity spans/fairy primitives,
  `sidebar.py` the state editor and configuration cards, `play.py` the Play
  tab, `registry.py` the live/finished agent registry, `progress.py` the live
  progress title and registry loop, `plan_view.py` the plan timeline and its
  details, `sources_view.py` the game and wiki source panels, `trace_view.py`
  the audit/state/memory sections, `issues.py` the validation tables and chips,
  `tasks.py` the background planning/evaluation workers plus the cached graph,
  and `evaluation_view.py` the Evaluation tab. The frontend requires a configured
  LLM provider, with local providers supported for offline runs. The page uses
  the Majora's Mask theme injected by `_inject_styles()` (Cinzel/Inter, dark
  navy surfaces, gold/teal/red accents in `.streamlit/config.toml` and the
  `_THEME_CSS` block). The sidebar is the state editor: brand block, language
  picker, the "time left" card with the three-day bar, Day 1-3 and a 24-hour
  time (minute precision, default 06:00), location, masks, items, completed
  objectives (stored by id, grouped by quest, never inferred from the
  location), quests, Save/Load and the read-only settings from
  `app/settings.py`.
  `00:00-05:59` is mapped to hours 24-29 internally so it stays the night at
  the end of the selected game day. `_render_sidebar_editor()` owns those
  widgets and returns the values the Play tab turns into a `GameState`.
  The page has
  two top-level tabs: *Play* (`_render_play()`, TaIA's greeting, the inline
  goal input with the Ask TaIA/Stop controls, the empty-plan card, the live or
  finished agent registry, and the timeline plan) and
  *Evaluation* (`_render_evaluation(editor)`, TaIA's greeting and the sweep:
  scenario picker, RAG toggle, Run/Stop, native metrics, an HTML per-scenario
  table, the comparison card against the newest stored sweep, and
  *Load last report* for the sweep persisted by the worker).
  The plan renders as a vertical HTML timeline (`_render_plan()`; the last step
  and every step with an error are red, while step actions live in the *Why*
  tab) and the Critic's verdict as a teal/red banner (`_verdict_html()`). An
  invalid plan also shows the missing-requirement chips, the full problems
  table and the full *last plan* with the first failing step highlighted.
  Below it, *Behind the scenes* reuses three tabs with HTML detail cards for
  the step explanations, the game/RAG sources and the trace.
  Planning runs
  as a session-scoped background task: Generate is disabled while active and
  Stop requests cooperative cancellation between agent/LLM calls. The same HTML
  agent registry is used live and after the run: a row appears only when its
  agent starts, the last row stays open, a live row shows its Activity timeline
  (completed events dimmed, the current one highlighted) and swaps to the result
  body when the node finishes; future agents are never shown. The reasoning title
  rotates on a wall-clock timer (`_TICK_SECONDS`), while `_planning_live` blocks
  on the worker queue, repaints the registry only on a new event and the title on
  a tick, so nothing flickers. The single empty placeholder is an invisible yield
  point that lets Streamlit process a queued Stop click during a long agent call
  (`_IDLE_WAIT`). HTML `<details>` state is client-side, so a registry repaint
  resets an opened past row to its default; the current row stays open. The task
  keeps an ordered replayable log plus per-node timings, so the same registry
  gains engine badges, real durations, result summaries and every
  planning/critic attempt as the run completes; invalid runs add a red
  problem-count pill and the per-attempt issue table. The worker run is wrapped
  in `pipeline_span`, and the
  Trace tab's audit section
  shows the run id, a Phoenix link, the node timeline and errors only (in
  `st.code`); full LLM prompts are deliberately not shown in the UI. The
  worker streams the graph directly (not via `run_pipeline`), so it also
  rebuilds the final state from the stream chunks and posts the Critic's
  verdict to Phoenix as `plan/validation` itself, after its root span
  closed (same best-effort publication as `run_pipeline`, via
  `app/phoenix.py`).
* `app/progress.py` — the streaming progress seam: `report()` publishes custom
  LangGraph events and is a silent no-op outside a stream (headless, tests). The
  graph wraps each node to announce its start, and the Knowledge and Planning
  agents publish phase events (objectives, MCP data, wiki search/fetch/index,
  second retrieval, LLM call). The retriever takes an optional `on_progress`
  callback, so RAG stays decoupled from LangGraph.
* `app/trace.py` — OpenTelemetry tracing seam. `setup_tracing()`
  (called from `main.py` and `app/__main__.py`) installs a `TracerProvider`
  that exports over OTLP/HTTP when `OTEL_EXPORTER_OTLP_ENDPOINT` is set (e.g.
  the local Phoenix container) and is a cheap no-op otherwise, so tests, the
  demo and CI never need a backend. Every span carries the OpenInference
  attributes Phoenix reads for its dashboard — `openinference.span.kind`
  (`CHAIN`/`TOOL`/`RETRIEVER`/`LLM`), `input.value`/`output.value`, and an
  explicit `OK`/`ERROR` status set before the span closes. `pipeline_span()`
  opens one root span per
  run and feeds a per-run in-memory `RunTrace` (run id, the root span's
  `span_id`/`trace_id` for report↔trace links, node timeline, errors)
  that the UI reads; `current_span_ids()` exposes those ids per context (so a
  background sweep and a UI run cannot mix them up) and `flush_spans()` pushes
  queued spans before annotations are posted. `span()` traces one MCP call, the RAG retrieval or a
  validation and records failures; use `set_output()` inside the block for the
  output payload. `TraceCallback` is a LangChain callback
  attached at the single LLM call site: it puts the complete system/user/
  assistant prompts into `gen_ai.*` spans (for Phoenix) and writes the same
  prompts to console logs at `INFO`, bounded by `LLM_LOG_PAYLOAD_LIMIT`. Spans
  carry the OpenInference GenAI message attributes (`gen_ai.prompt.N.role`/
  `.content` and `gen_ai.completion.N.*`) so Phoenix renders each message with
  its role instead of one concatenated `input.value` blob — the LLM call itself
  always receives distinct message objects; the concatenation is display-only.
  Payload limits are constants (`LLM_LOG_PAYLOAD_LIMIT`, `SPAN_PAYLOAD_LIMIT`),
  not env vars; the only tracing env var is the endpoint.
* `app/__main__.py` — headless pipeline demo (`python -m app`); it also prints
  the run id, node timeline and any errors after the plan.
* `docker-compose.yml` — local observability stack: the Arize Phoenix
  container (web UI and OTLP/HTTP receiver share `:6006`; Phoenix has no
  `:4318` listener — that port belongs to the generic OTel Collector). The
  Streamlit app runs on the host; start this with `docker compose up -d` and
  set `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:6006` to export spans. The
  app is fully functional (no-op tracing) when it is not running.
* `tests/` — domain model, validation, re-planning, temporal reachability,
  RAG corpus/retrieval, tracing and Knowledge Agent integration tests,
  including hermetic wiki/cache scenarios. `test_reachability.py` pins the
  dead-branch closure and `test_temporal_matrix.py` is the deterministic
  clock matrix (no LLM) over the whole three-day cycle.

## Tooling

* Package manager: **uv**. Install with `uv sync`, run with `uv run`.
  No `requirements.txt`, no pip.
* Lint/format: **ruff** (E, F, I rules). Always run
  `uv run ruff check .` and `uv run ruff format .` before considering a
  change complete.
* Tests: **pytest** via `uv run pytest`.
* Commit messages always use Conventional Commit prefixes
  (`feat`, `fix`, `chore`, `test`, `docs`, ...).
* Commands:

  ```sh
  uv sync                                             # install deps + project
  uv run ruff check .                                 # lint
  uv run ruff format .                                # format
  uv run pytest                                       # tests
  uv run python -m app                                # headless pipeline demo
  uv run streamlit run main.py                        # Streamlit UI
  ```

## Git Workflow

* The default branch is `main`.
* Feature work happens on dedicated branches:
  `feat/<feature-name>` or `fix/<fix-name>`.
* Never use `phase` in branch names: name the branch after the feature
  (`feat/npcs-schedules-events`), never after a project phase.
* Never reference project phases in `README.md`: the phases live in `TODO.md`
  only.
* Open pull requests with `gh` following `.github/pull_request_template.md`
  (Description/Type/Checks/Workflow) and wait for review; the maintainer
  reviews and merges them (never self-merge).
* Never open a pull request unless the maintainer explicitly asks for it.
* PR titles and descriptions must always be written in English.

## Maintaining AGENTS.md

`AGENTS.md` is a living document.

Update it when the **architecture, major components, agent responsibilities, or project-wide development conventions** change.

Do not update it for every small implementation change or bug fix.

It should describe how the project **currently works**, not a history of previous ideas.
