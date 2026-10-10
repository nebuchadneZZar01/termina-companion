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
context. Persistent memory, broader tracing and formal plan evaluation remain
future work; leave clear extension points for them.

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
  ClockTime/TimeWindow, Plan, ValidationResult).
* `app/data/mock_knowledge.py` — game data (areas, quests, objectives,
  NPCs, events, windows, mask/item requirements). Data covers several
  major areas but is deliberately NOT lore-complete; do not tie the
  architecture to one quest. Agents never access this directly — they go
  through the MCP tools in `app/mcp/tools.py`.
* `app/agents/` — one module per agent (state, knowledge,
  planning, critic), each exposing a LangGraph node function `run(state) -> dict`.
  State, Knowledge and Critic run deterministic rule-based logic. The Planning
  Agent always calls the configured LLM; missing configuration, invocation
  errors and empty output fail explicitly. LLM output is post-processed
  deterministically: refs, titles and locations are grounded to the knowledge
  objectives and each step's window is clamped inside its objective's slot
  (see `app/agents/planning_agent.py`). The final plan is then rebuilt against the
  authoritative objective chain: `search_quests` retrieves a whole quest when
  any of its objectives matches, "obtain item" steps are pruned when the
  player already owns what they provide (`provides_items`/`provides_masks` on
  `Objective`), missing chain steps are re-inserted in prerequisite order and
  `depends_on` is recomputed; on replan attempts kept steps are re-slotted onto
  a 1h window after their dependencies end, where the LLM's windows are only
  advisory. The Knowledge Agent calls MCP tools in-process for authoritative
  structured data, then calls `app.rag.retriever.retrieve` for adaptive wiki
  evidence. Retrieval runs immediately before planning; RAG failure is logged
  and degrades to structured context, never changing the objective chain.
* `app/mcp/` — MCP tools and server. `app/mcp/tools.py` holds the pure
  tool functions (search_quests, get_npc_schedule, get_quest_info, get_event,
  get_location, check_prerequisites) — the single seam between agents and
  game data. `app/mcp/server.py` wraps them as a `MCPServer` for external
  MCP clients. The Knowledge Agent imports tools directly for in-process use;
  RAG is not exposed as an MCP tool.
* `app/rag/` — adaptive supplemental RAG package: Pydantic document/chunk/
  evidence/source-manifest contracts, MediaWiki client and HTML cleanup,
  heading-aware chunking, FastEmbed adapter, persistent embedded Qdrant store,
  ingestion lock and cache-aside retrieval. `retrieve` is the Knowledge Agent
  seam; it always attempts retrieval, records `cache_hit`/`wiki_ingested`/
  `wiki_miss`/`unavailable`, and fails soft without bypassing MCP authority. A
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
  trajectories.
* `app/llm.py` — LLM provider factory (`get_chat_model()`); raises
  `LLMConfigurationError` when no usable provider is configured. The Planning
  Agent has no rule-based fallback.
* `app/state.py` — `PlanningState`, the workflow state threaded
  through the graph (Pydantic model, used as the LangGraph state schema),
  including retrieved evidence, indexed-source manifest and retrieval status.
* `app/graph.py` — graph wiring and the bounded re-planning
  loop (max `MAX_PLANNING_ATTEMPTS = 3`) driven by the Critic Agent. Each node is
  wrapped to announce its start on the custom progress stream.
* `app/ui.py` — Streamlit frontend logic (`render()`); requires a configured
  LLM provider, with local providers supported for offline runs. Planning runs
  as a session-scoped background task: Generate is disabled while active and
  Stop requests cooperative cancellation between agent/LLM calls. The progress
  stepper grows with the run instead of redrawing itself: the outer status title
  rotates on a wall-clock timer (`_TICK_SECONDS`), and a child step is appended
  only when its agent starts, so future agents are never shown. Each step has a
  bold "Activity" timeline (completed events dimmed, the current one highlighted)
  separated from a labelled result card, so what the agent did and what it
  produced stay distinct; the agent name and engine badge live in the step header
  only. `_planning_live` blocks on the worker queue and repaints only on a
  new event or a timer tick, so nothing flickers; the single empty placeholder is
  an invisible yield point that lets Streamlit process a queued Stop click during
  a long agent call (`_IDLE_WAIT`). The task keeps an ordered replayable log, so
  the finished stepper is re-rendered statically after the final rerun.
* `app/progress.py` — the streaming progress seam: `report()` publishes custom
  LangGraph events and is a silent no-op outside a stream (headless, tests). The
  graph wraps each node to announce its start, and the Knowledge and Planning
  agents publish phase events (objectives, MCP data, wiki search/fetch/index,
  second retrieval, LLM call). The retriever takes an optional `on_progress`
  callback, so RAG stays decoupled from LangGraph.
* `app/__main__.py` — headless pipeline demo (`python -m app`).
* `tests/` — domain model, validation, re-planning, RAG corpus/retrieval and
  Knowledge Agent integration tests, including hermetic wiki/cache scenarios.

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
* Never use `phase` in branch names (`feat/npcs-schedules-events`, not
  `feat/phase3-game-knowledge`).
* Open pull requests with `gh` and wait for review; the maintainer reviews
  and merges them (never self-merge).
* PR titles and descriptions must always be written in English.

## Maintaining AGENTS.md

`AGENTS.md` is a living document.

Update it when the **architecture, major components, agent responsibilities, or project-wide development conventions** change.

Do not update it for every small implementation change or bug fix.

It should describe how the project **currently works**, not a history of previous ideas.
