"""The four planning agents as LangGraph nodes.

Each module exposes a single node function of the shape
``(state: PlanningState) -> dict``. Mock logic is deterministic;
the LLM swap happens inside each node without changing the graph wiring.
"""
