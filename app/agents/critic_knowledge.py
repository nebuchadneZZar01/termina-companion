"""Memoized knowledge view used by the Critic Agent.

The Critic must not trust the plan step fields the planner produced, so it
resolves every reference against the authoritative game data through the MCP
tools. This view caches each lookup for the duration of one validation, and
lets tests inject explicit objective/NPC overrides.
"""

from __future__ import annotations

import logging

from app.data.mock_knowledge import NPC, Objective, Quest
from app.domain import TimeWindow
from app.mcp.tools import get_npc_schedule, get_objective, get_quest_info
from app.trace import set_output
from app.trace import span as traced_span

logger = logging.getLogger(__name__)


class KnowledgeView:
    """Per-validation cache over the MCP game-knowledge tools.

    Explicit ``objectives`` and ``npcs`` overrides take precedence over the
    knowledge base and are how tests supply synthetic data. Every cache miss
    is one traced MCP tool call; a cache hit never touches the backend.
    """

    def __init__(
        self,
        objectives: list[Objective] | None = None,
        npcs: list[NPC] | None = None,
    ) -> None:
        """Seed the cache with caller-provided overrides.

        args:
            objectives (list[Objective] | None, default None): objectives that
                win over the knowledge base.
            npcs (list[NPC] | None, default None): NPCs that win over the
                knowledge base.

        returns:
            None: the instance caches the overrides.
        """
        self._objectives = {obj.id: obj for obj in objectives or []}
        self._npcs = {npc.id: npc for npc in npcs or []}
        self._quest_of: dict[str, str] = {}
        self._quests: dict[str, Quest | None] = {}

    def objective(self, ref: str) -> Objective | None:
        """Resolve an objective reference to its authoritative objective.

        args:
            ref (str): the objective id to resolve.

        returns:
            Objective | None: the objective, or None when the ref is empty,
            unknown or the tool call fails.
        """
        if not ref:
            return None
        cached = self._objectives.get(ref)
        if cached is not None:
            return cached
        try:
            return self._fetch_objective(ref)
        except ValueError:
            return None
        except Exception as exc:  # noqa: BLE001 - degrades to an unknown ref
            logger.warning("Critic: get_objective(%s) failed: %s", ref, exc)
            return None

    def _fetch_objective(self, ref: str) -> Objective:
        """Fetch an objective through the tool and cache it with its quest id.

        args:
            ref (str): the objective id.

        returns:
            Objective: the authoritative objective.

        raises:
            Exception: whatever the tool raises, for the caller to degrade.
        """
        with traced_span("mcp.get_objective", kind="TOOL", input_value=ref) as tool_span:
            payload = get_objective(ref)
            set_output(tool_span, payload)
        objective = Objective.model_validate(payload["objective"])
        self._objectives[ref] = objective
        self._quest_of[ref] = payload["quest_id"]
        return objective

    def quest_id(self, ref: str) -> str | None:
        """Return the quest an objective belongs to.

        args:
            ref (str): the objective id.

        returns:
            str | None: the owning quest id, or None when the ref is unknown
            or was supplied as an override.
        """
        if self.objective(ref) is None:
            return None
        return self._quest_of.get(ref)

    def quest_for_objective(self, ref: str) -> Quest | None:
        """The quest that owns an objective, resolving caller overrides too.

        ``quest_id`` keeps returning None for an override, because a caller can
        supply synthetic objectives. A verdict needs the quest's name, so this
        variant asks the tool for the owner when the cache does not know it.

        args:
            ref (str): the objective id.

        returns:
            Quest | None: the owning quest, or None when it cannot be resolved.
        """
        if self.objective(ref) is None:
            return None
        if ref not in self._quest_of:
            try:
                self._fetch_objective(ref)
            except Exception as exc:  # noqa: BLE001 - degrades to no quest name
                logger.warning("Critic: owner of %s unknown: %s", ref, exc)
                return None
        return self.quest(self._quest_of[ref])

    def quest(self, quest_id: str) -> Quest | None:
        """Resolve a quest id to its authoritative quest.

        args:
            quest_id (str): the quest id to resolve.

        returns:
            Quest | None: the quest, or None when it is unknown or the tool
            call fails. Failures are cached for the rest of the validation.
        """
        if quest_id in self._quests:
            return self._quests[quest_id]
        try:
            with traced_span("mcp.get_quest_info", kind="TOOL", input_value=quest_id) as tool_span:
                payload = get_quest_info(quest_id)
                set_output(tool_span, payload)
        except Exception as exc:  # noqa: BLE001 - degrades to an unknown quest
            logger.warning("Critic: get_quest_info(%s) failed: %s", quest_id, exc)
            self._quests[quest_id] = None
            return None
        quest = Quest(
            id=payload["id"],
            name=payload["name"],
            objectives=[Objective.model_validate(item) for item in payload["objectives"]],
        )
        self._quests[quest_id] = quest
        return quest

    def npc(self, npc_id: str) -> NPC | None:
        """Resolve an NPC id to its schedule.

        args:
            npc_id (str): the NPC id to resolve.

        returns:
            NPC | None: the NPC with structured schedule windows, or None when
            the id is empty, unknown or the tool call fails.
        """
        if not npc_id:
            return None
        cached = self._npcs.get(npc_id)
        if cached is not None:
            return cached
        try:
            with traced_span("mcp.get_npc_schedule", kind="TOOL", input_value=npc_id) as tool_span:
                payload = get_npc_schedule(npc_id)
                set_output(tool_span, payload)
        except Exception as exc:  # noqa: BLE001 - degrades to no schedule
            logger.warning("Critic: get_npc_schedule(%s) failed: %s", npc_id, exc)
            return None
        npc = NPC(
            id=payload["id"],
            name=payload["name"],
            location=payload["location"],
            schedule=[TimeWindow.model_validate(window) for window in payload.get("windows", [])],
        )
        self._npcs[npc_id] = npc
        return npc
