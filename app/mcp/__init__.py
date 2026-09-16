"""MCP game-knowledge tools and the Termina MCP server.

Game data access lives here: the tool functions in ``tools.py`` are plain
callables shared between the in-process agent path and the protocol server in
``server.py``. This is the single seam between the agents and game data.
"""

from app.mcp.server import mcp
from app.mcp.tools import (
    check_prerequisites,
    get_event,
    get_location,
    get_npc_schedule,
    get_quest_info,
    search_quests,
)

__all__ = [
    "mcp",
    "search_quests",
    "get_npc_schedule",
    "get_quest_info",
    "get_event",
    "get_location",
    "check_prerequisites",
]
