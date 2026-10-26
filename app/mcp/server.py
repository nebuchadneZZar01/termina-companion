"""Termina MCP server exposing the game-knowledge tools.

The tool functions in ``app.mcp.tools`` are registered here as protocol tools,
so any MCP host (Claude Desktop, the test client, a remote caller) can call
them. The Knowledge Agent keeps using the same functions in-process; run this
standalone with ``uv run python -m app.mcp.server``.
"""

from __future__ import annotations

from mcp.server import MCPServer

from app.mcp.tools import (
    check_prerequisites,
    get_event,
    get_location,
    get_npc_schedule,
    get_objective,
    get_quest_info,
    search_quests,
)

mcp = MCPServer(
    "termina-companion",
    instructions=(
        "Game knowledge for Majora's Mask planning. Use search_quests to find "
        "quests relevant to the player's goal, get_objective or get_quest_info "
        "to resolve the authoritative objective fields, get_npc_schedule, "
        "get_event and get_location for the details the planner needs, and "
        "check_prerequisites to verify an objective is feasible."
    ),
)

_TOOLS = (
    search_quests,
    get_npc_schedule,
    get_quest_info,
    get_objective,
    get_event,
    get_location,
    check_prerequisites,
)
for _tool in _TOOLS:
    mcp.tool()(_tool)


if __name__ == "__main__":
    mcp.run()
