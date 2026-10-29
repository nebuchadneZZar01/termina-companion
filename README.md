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
past episodes), OpenTelemetry tracing and a plan-evaluation harness are
active; persistent memory remains future work.

## Install

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync
```

## Run the Streamlit UI

```sh
uv run streamlit run main.py
```

Edit the game day, clock time, location, inventory, masks and quest progress
(use the sidebar Save/Load buttons to keep the state between sessions), set a
goal, then press **Generate plan**. The clock uses game days: pick **Day 1**,
**Day 2** or **Day 3** and a 24-hour time. Each game day runs from **06:00 to
05:59 the next morning**, so `00:00-05:59` is the night at the end of the
selected day, not the start of the next one. The default is Day 1, 06:00.
The UI shows retrieved knowledge, RAG status, the
indexed-page manifest, retrieved evidence provenance, plan steps and validation
outcome. While the agents run, **Generate plan** is disabled and **Stop** can
request cooperative cancellation after the current agent or LLM call. The
progress stepper is not on a timer: it repaints only when an agent finishes, so
the page stays still while the agents reason.

The page has two tabs: **Play** (the state editor and the planning flow) and
**Evaluation** (the evaluation sweep, see below).

## Temporal reachability and the Song of Time

The three days are one finite timeline. An objective's window is a dated
occurrence inside that timeline, not a slot that comes back tomorrow: once the
window is over, everything that needed it is over too, and only the Song of Time
reopens it.

The one explicit exception is a **recurring** objective — a daily availability
such as a place to visit or an NPC to talk to. It repeats on every game day with
the same time of day and the same duration (a nightly window keeps running past
midnight inside the same game day), so it never falls into the past. Dated
scenes (the Anju & Kafei chain, the Bombers, Romani Ranch) stay one-off.

What the pipeline does with that:

- the planner never schedules a step at an hour that has already gone by; an
  objective whose window has closed has no slot to give, so it is left out of the
  plan and out of the LLM context. When nothing is left, no LLM call is made: the
  run returns an empty plan with the `unreachable` engine badge.
- expiry propagates through `prerequisites` and through the `requires_quests`
  gate between quests. A dead prerequisite strands its transitive successors, a
  quest that can no longer be completed strands the objectives gated behind it,
  and unrelated quests stay plannable.
- explicit progress never expires. An objective listed under **Completed
  objectives** (sidebar), a quest marked done, and any objective whose reward the
  player already holds are treated as done and are never reported as unreachable.
- the budget is checked, not only the dates. Each step needs an hour and the
  chain is scheduled in order, so a goal can fail simply because what is left of
  the cycle cannot hold the whole chain: six one-hour objectives in the last two
  hours of Day 3 no longer fit. Every objective that stops fitting is reported
  with its own issue, the end of its last availability and the Song of Time.
- the verdict is a failure with `unreachable` issues, one per dead chain or per
  objective that no longer fits, naming the quest, the missed objective, the end
  of its availability and the Song of Time. The plan still lists the steps that
  are feasible, so a partly closed goal shows both what can be done and what has
  to wait for a new cycle. The graph does not re-plan on these issues: a new
  attempt cannot change the clock.
- a plan can no longer pass while it silently lost a step. The Critic rebuilds
  the same schedule from the objectives and the clock and compares the plan with
  it: an objective that still fits but has no step is a `missing_step` error.
- a gate towards a quest that is merely incomplete is still `quest_prerequisite`
  ("complete this quest first"). It becomes `unreachable` only when that quest can
  no longer be completed either.

Partial progress is never inferred from the player's location: select the
objectives you already did in the sidebar. Saves carry them in version 3; version
2 files still load unchanged.

The closure lives in `app/agents/reachability.py` (`dead_objectives`,
`dead_quests`), the availability arithmetic in `occurrences()` in
`app/agents/planning_clock.py`, and the shared scheduling decision in
`app/agents/scheduling.py` (`select_chain`, `schedule_chain`). The behaviour is
pinned by `tests/test_reachability.py`, `tests/test_scheduling.py` and the
deterministic clock matrix in `tests/test_temporal_matrix.py`.

## Save/Load

The sidebar has **Save** and **Load** buttons for the current game state
(day/time, location, masks, inventory, quest progress and goal).

Saves are written as JSON to `saves/last_save.json` (the directory is
derived from `RAG_QDRANT_PATH`, so it sits next to `.cache/`). **Load**
restores every form field from that file, including the completed objectives; if
no valid save exists the app shows a warning and keeps the current state. The
file is at version 3; version 2 saves (no completed objectives) load unchanged. Saves from the earlier absolute-day
clock are migrated to the game-day model on load: an old `Day 2 02:00` becomes
`Day 1 02:00 (+1)`, while invalid pre-dawn Day 1 times clamp to `Day 1 06:00`
with a warning.

## Run the headless demo

```sh
uv run python -m app
```

The demo prints understood state, structured MCP knowledge, adaptive RAG
status/evidence, the generated plan and validation. Configure an LLM first;
Ollama or LM Studio work locally without an external API key.

## Run with an LLM

LLM configuration is done **only via environment variables** (no UI fields).

```sh
export LLM_PROVIDER=openai
export LLM_API_KEY=sk-...
uv run streamlit run main.py
```

Supported providers: `openai`, `openrouter`, `ollama`, `lmstudio`, `anthropic`,
`google`. Configure `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY` and
`LLM_BASE_URL` (or set them in `.env`); `.env.example` is the complete
annotated reference. Missing configuration, invocation errors and empty model
output fail explicitly. The Planning Agent never substitutes a fallback plan.

Ollama and LM Studio serve the OpenAI-compatible API under `/v1`, so use
`LLM_BASE_URL=http://localhost:11434/v1` (or leave it empty to get the
provider default). A base URL naming only the host is normalized to `/v1`
automatically, and a failed call names the setting to check (`LLM_BASE_URL`,
`LLM_API_KEY` or the server itself).

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
usage and latency). `PHOENIX_BASE_URL` optionally overrides where span
annotations are posted when it differs from the OTLP endpoint (default: reuse
the OTLP endpoint). Full prompts also go to console logs at `INFO`, bounded in
length by `LLM_LOG_PAYLOAD_LIMIT` so one runaway prompt cannot flood the
console. In the app, the Trace tab shows the
`run_id`, the node timeline and any errors — errors only, no prompt bodies.

### Scores in Phoenix

Every run's trace carries the Critic's verdict as a span annotation,
`plan/validation`: score 1/0 with a `PASS`/`FAIL` label, the feasibility
issues in the explanation, and the run metadata (goal, attempts, model). A
run that crashed before the Critic kept its ERROR span and gets no
annotation.

An evaluation sweep (CLI or the *Evaluation* tab) adds the harness scores
to the same traces, visible in the **Annotations** panel of the run's root
span:

* `evaluation/overall` — score 1/0 with a `PASS`/`FAIL` label and an
  explanation naming what failed (the failed checks, or the run error);
* one `evaluation/<kind>` annotation per **failed** check (score 0);
* warnings (like `proposal_fidelity`) get the same annotation with a `warning`
  label and **no score**, so they never read as a failure.

A feasible plan that the harness still rejects (`plan/validation` PASS,
`evaluation/overall` FAIL) means the run built something executable that
missed the quest's goal — a useful signal about the planner, not a bug in
either check.

Publishing is best-effort telemetry: without a configured endpoint it is a
no-op, and an unreachable Phoenix logs a warning without failing the run or
the sweep.

## Adaptive Zelda Wiki RAG

RAG is supplemental and on by default (`RAG_ENABLED=0` switches the wiki leg
off for A/B evaluation). There is no static curated corpus: Zelda Wiki is the
only RAG source. Structured MCP data
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

Copy `.env.example` to `.env` or export these variables. All of them go
through `app/settings.py` (Pydantic settings), so an invalid value fails at
startup instead of halfway through a run.

| Variable | Default | Purpose |
|---|---|---|
| `RAG_ENABLED` | `1` | Supplemental wiki retrieval switch; `0`/`false`/`off`/`no` keeps structured MCP answers only. |
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
which is implemented in the next section.

## Evaluation

The evaluation harness measures whether a plan produced by the pipeline
actually reaches the player's goal. It ships nine scenarios — one per quest,
spanning every game area — each with a player state, a goal phrased the way a
player would phrase it, and the objectives the plan is expected to contain:

| Scenario | What it covers |
|---|---|
| `anju-kafei` | Nine-step main chain over three days: Kafei's Mask, Room Key, letter, pendant, Sakon's Hideout and the reunion |
| `bombers-notebook` | A notebook earned from the leader unlocks the hidden hideout |
| `darmani-ghost` | Longest mask chain, night meeting at 22:00, lullaby the next day |
| `mikau-eggs` | The Zora Mask gates every later step, eggs need a daytime window |
| `mikau-with-zora-mask` | The Zora Mask is already owned, so the shore step must be skipped |
| `pamela-father` | Night-only slots after midnight (00:00-04:00) behind the Gibdo Mask |
| `deku-princess` | Two-day chain through the Southern Swamp, gated by the Deku Mask |
| `romani-ranch` | Early-morning purchase, 02:00 alien defence, moonlit milk delivery |
| `deed-chain` | Five-step trade cycle across three areas and all three days |

The evaluator is deterministic and never calls an LLM. It reads game knowledge
only through the MCP tools (`search_quests`, `check_prerequisites`), so it
measures what the Knowledge Agent could have known, and it runs nine checks:

| Check | Fails when |
|---|---|
| `plan_shape` | No plan, a step count outside the expected range, or a step referencing an unknown objective |
| `objective_achievement` | A required objective is missing, the goal objective is not reached, or a forbidden objective is present |
| `temporal_ordering` | Steps are out of order, overlap, start in the past, or fall outside their objective's slot |
| `prerequisites` | A step's items, masks or prerequisite objectives are not satisfied when it happens |
| `tool_usage` | The Knowledge Agent skipped a tool the goal needed (quest search, NPC schedule, event) |
| `critic` | The Critic rejected the plan |
| `trajectory_order` | The run produced its plan without consulting the MCP tools, or without a Critic verdict |
| `replan_bound` | The run overshot `MAX_PLANNING_ATTEMPTS` (a late acceptance is a warning) |
| `proposal_fidelity` | The LLM's raw proposal omitted expected objectives the deterministic rebuild had to add (warning) |

The last three evaluate the **trajectory** — how the run reached its plan, not
only what came out. They only fire on a recorded run (the planner exposes its
untouched proposal before reconciliation, and the Critic appends one
`AttemptRecord` per attempt); a plan evaluated on its own is exempt.

A scenario passes when no check reports an error; warnings are reported but do
not fail it. A run that crashes (LLM error, no plan produced) is a failure
carrying the error message — it is never reported as a scenario without
issues.

The pipeline's own Critic and the harness answer different questions. The
Critic runs inside every planning run and checks **feasibility** — items,
masks, prerequisite objectives, temporal overlap — and triggers re-planning
when the plan cannot be executed. The harness checks **goal achievement**
against the scenario's expectations: a plan can be perfectly feasible and
still fail because it never reached the quest's objective (think of a
feasible detour that ignores the Romani Remedy entirely). The `critic` and
`trajectory_*` checks above verify that the Critic ran and what it decided;
they do not replace it. A verdict mismatch between the two — feasible, but
wrong goal — is a useful signal about the planner, not a bug in either check.

### CLI

```sh
uv run python scripts/evaluate_plans.py --list
uv run python scripts/evaluate_plans.py
uv run python scripts/evaluate_plans.py --scenario anju-kafei --repeat 3
uv run python scripts/evaluate_plans.py --rag off
uv run python scripts/evaluate_plans.py --json reports/evaluation.json
```

The harness runs the full pipeline once per scenario, so it needs a configured
LLM provider (like the rest of the app). It prints one `PASS`/`FAIL` line per
scenario with the failed checks, then the aggregate pass rate, and exits `1`
when any scenario fails — so it can gate a run:

```
[1/9] anju-kafei             PASS  (12.4s)
[2/9] bombers-notebook       PASS  (9.8s)
...
Pass rate: 9/9 = 1.00
Failures by check: none
```

The memory store is cleared before every scenario, so the scenarios never see
each other's past episodes. `--rag off` disables the supplemental wiki
retrieval (`RAG_ENABLED=0`) to compare plan quality with and without it.

Every run also writes its report to the shared store
(`app/evaluation/storage.py`): `last_evaluation.json` in the save directory
derived from `RAG_QDRANT_PATH` (`.cache/saves/` by default, gitignored) plus a
timestamped copy in `evaluations/` underneath it. `--json` writes an extra
copy at an explicit path. The report records its sweep metadata — the RAG
flag, the model that produced each plan, the repeat count and a creation
timestamp — so two saved sweeps can be compared instead of retyped from the
terminal.

Each sweep is also compared with the newest compatible stored one (the same
wiki flag is preferred; `--baseline PATH` picks another report explicitly).
A scenario that passed before and fails now is printed as a regression with the
check that broke it, a scenario that improved is noted, and a scenario present
on only one side is reported as `new`/`missing`: a partial sweep never looks
like a quality drop. The comparison does not change the exit code — a
regression is already a failing scenario.

The wiki-retrieval label is derived from what each run actually recorded, not
from the flag the sweep was started with: a run whose wiki leg died partway
(store locked, wiki unreachable) is reported as `degraded`, because a sweep
that printed `on` while silently falling back to structured context would
otherwise be compared against a healthy one. `wiki_miss` is not degraded — it
is also the ordinary outcome of a wiki with nothing relevant for a query.

### Evaluation tab

The same sweep runs in the browser: open the app and switch to the
**Evaluation** tab, pick the scenarios, and press *Run evaluation*. The sweep
runs in a background thread with a progress bar and a cooperative *Stop*
control, then shows the pass rate, a per-scenario table and the failed checks
of every scenario. Both entry points share `app/evaluation/runner.py`, so they
measure exactly the same thing.

The sweep is saved to the same store when it finishes — from the worker
thread, so a closed tab loses nothing — and *Load last report* brings the
checks back after a browser reload. Under the metrics, a comparison card
checks the report against the newest stored sweep and warns when a scenario
regressed, so a reloaded report still tells you what changed.

### What the pass rate measures

The Planning Agent rebuilds the objective chain deterministically after the
LLM answers (`_reconcile_plan`), so the step set of a plan follows from the
retrieved objectives and the LLM mainly influences the step windows. The pass
rate is therefore mostly a regression signal over retrieval, chain
reconciliation and the critic — not a measure of LLM creativity. The
`proposal_fidelity` warnings are where the LLM's own contribution shows: how
often its raw proposal already contained the expected objectives. The warning
names the omitted objectives by title and explains that the deterministic
rebuild added them, so it never hides behind the internal refs.

## Architecture

```text
Game State → State Agent → Knowledge Agent → Planning Agent
          → Critic/Validator → Plan   (bounded re-planning loop on failure)
```

The LangGraph workflow has four nodes, one module per agent under
`app/agents/`. Agent responsibilities remain separate. Planning output is
post-processed deterministically: references, titles and locations are grounded
to MCP objectives, duplicate steps are removed, windows are clamped to the
objective's next open availability (never before the player's clock), objectives
whose window has closed are dropped, and the authoritative prerequisite chain is
rebuilt before validation. The Critic re-reads requirements and dependency timing from those
objectives through the MCP tools, so a grounding mistake in a step cannot hide
an infeasibility.

| Agent | Input | Output | Engine |
|---|---|---|---|
| **State Agent** | `GameState`, `Goal` | Canonical state and summary | Rule-based state normalization and summary. |
| **Knowledge Agent** | `GameState`, `Goal` | Objectives, schedules, events, RAG evidence and context | Rule-based MCP plus adaptive RAG; RAG failure degrades to structured context. |
| **Planning Agent** | State summary and retrieved context | `Plan` | Configured LLM with deterministic grounding and temporal post-processing. |
| **Critic Agent** | `Plan`, state and objectives; knowledge resolved through MCP tools | `ValidationResult` | Rule-based feasibility checks from authoritative objectives (requirements, dependency timing, overlaps, temporal reachability) and bounded re-planning trigger. |

| Component | Responsibility |
|---|---|
| `app/domain.py` | Pydantic game-state, goal, plan and validation contracts. |
| `app/data/mock_knowledge.py` | Structured demo data; the Knowledge Agent and the Critic read it through the MCP tools, while the State Agent and the planning chain still read `build_default_knowledge()` (see `TODO.md`). |
| `app/mcp/` | Pure game-data tools and external MCP server; authoritative knowledge seam. |
| `app/agents/` | State, Knowledge, Planning and Critic graph nodes, plus `progress.py` (explicit objective progress) and `reachability.py` (what the clock has closed). |
| `app/rag/` | Adaptive wiki client, cleanup/chunking, FastEmbed adapter, Qdrant store and cache-aside retrieval. |
| `app/state.py` | `PlanningState`, including RAG evidence, status, warning, ingested pages and indexed-source manifest. |
| `app/graph.py` | LangGraph wiring and `MAX_PLANNING_ATTEMPTS = 3` loop. |
| `app/ui/` | Streamlit frontend, split by page, theme, formatting, sidebar, plan, sources, registry, progress, trace, issues, tasks and evaluation. |
| `app/evaluation/` | Plan-evaluation scenarios, deterministic evaluator, shared sweep runner and report storage. |
| `scripts/evaluate_plans.py` | CLI harness for the evaluation sweep. |
| `app/trace.py` | OpenTelemetry tracing seam: run spans, LLM prompt capture and the no-op/OTLP setup. |
| `docker-compose.yml` | Local Arize Phoenix observability container. |
| `app/__main__.py` | Headless pipeline demo. |
| `tests/` | Domain, validation, graph, RAG persistence, tracing, evaluation and integration tests. |

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
- **Plan evaluation** — the scenario/plan evaluator and the trajectory checks
  are in place; the next step is comparing a sweep against the stored history
  to flag regressions (per-scenario deltas over pass rate, check kinds and
  `proposal_fidelity` warnings).
- **Next-cycle planning** — the Song of Time currently produces an infeasible
  verdict, not a plan for the new cycle. Planning across the restart needs
  cycle-bound item permanence in the knowledge base, a cycle reference on `Plan`
  anchored at Day 1 06:00, a Critic check against the shifted clock and an
  evaluation scenario.
