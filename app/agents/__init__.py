"""The four planning agents as LangGraph nodes.

Each module exposes a single node function of the shape
``(state: PlanningState) -> dict``. State, Knowledge and Critic use
deterministic domain logic; Planning calls an LLM by default and applies
deterministic grounding and reconciliation before validation. The
``PLANNER=deterministic`` engine skips the LLM call entirely: it is the
evaluation baseline, not the product path.
"""
