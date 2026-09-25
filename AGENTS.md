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

Do not implement RAG, persistent memory, tracing or evaluation prematurely. Leave clear extension points for them.

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
  advisory. The Knowledge Agent calls the MCP tools
  in-process to retrieve game knowledge.
* `app/mcp/` — MCP tools and server. `app/mcp/tools.py` holds the pure
  tool functions (search_quests, get_npc_schedule, get_quest_info, get_event,
  get_location, check_prerequisites) — the single seam between agents and
  game data. `app/mcp/server.py` wraps them as a `MCPServer` for external
  MCP clients. The Knowledge Agent imports tools directly for in-process use.
* `app/llm.py` — LLM provider factory (`get_chat_model()`); raises
  `LLMConfigurationError` when no usable provider is configured. The Planning
  Agent has no rule-based fallback.
* `app/state.py` — `PlanningState`, the workflow state threaded
  through the graph (Pydantic model, used as the LangGraph state schema).
* `app/graph.py` — graph wiring and the bounded re-planning
  loop (max `MAX_PLANNING_ATTEMPTS = 3`) driven by the Critic Agent.
* `app/ui.py` — Streamlit frontend logic (`render()`); requires a configured
  LLM provider, with local providers supported for offline runs.
* `app/__main__.py` — headless pipeline demo (`python -m app`).
* `tests/` — domain model, validation and re-planning tests.

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
