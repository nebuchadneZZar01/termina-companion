"""The four planning agents as LangGraph nodes.

Each module exposes a single node function of the shape
``(state: PlanningState) -> dict``. State, Knowledge and Critic use
deterministic domain logic; Planning always calls an LLM and applies
deterministic grounding and reconciliation before validation.
"""
