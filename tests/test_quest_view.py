"""The cached quest view agents read through the MCP tool seam."""

from __future__ import annotations

import ast
from pathlib import Path

from app.agents.quest_view import (
    load_quest,
    load_quests,
    objective_by_id,
    objective_positions,
    quest_index,
)
from app.data.mock_knowledge import build_default_knowledge

_AGENTS_DIR = Path(__file__).resolve().parents[1] / "app" / "agents"


def test_load_quests_matches_the_knowledge_base():
    """The tool payload validates back into the exact quest models."""
    kb = build_default_knowledge()
    assert load_quests() == kb.quests


def test_load_quests_returns_a_fresh_list():
    """A caller may sort or filter the list without touching the cache."""
    first = load_quests()
    first.clear()
    assert load_quests() == build_default_knowledge().quests


def test_objective_positions_match_every_objective():
    """Every objective maps to its quest and chain position."""
    expected = {
        objective.id: (quest.id, idx)
        for quest in build_default_knowledge().quests
        for idx, objective in enumerate(quest.objectives)
    }
    assert objective_positions() == expected


def test_quest_index_and_load_quest_resolve_through_the_view():
    """The index and the single lookup agree with the tool payload."""
    index = quest_index()
    assert set(index) == {quest.id for quest in load_quests()}
    assert load_quest("anju_kafei") is index["anju_kafei"]
    assert load_quest("unknown_quest") is None


def test_objective_by_id_resolves_and_returns_none():
    """A known objective resolves, an unknown id returns None."""
    objective = next(objective for quest in load_quests() for objective in quest.objectives)
    assert objective_by_id(objective.id) is objective
    assert objective_by_id("unknown_objective") is None


def test_agents_do_not_build_the_knowledge_base():
    """Agent modules must read game data through the MCP seam, not the KB."""
    offenders: list[str] = []
    for path in sorted(_AGENTS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported = isinstance(node, ast.ImportFrom) and node.module == "app.data.mock_knowledge"
            if imported and any(alias.name == "build_default_knowledge" for alias in node.names):
                offenders.append(path.name)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "build_default_knowledge":
                    offenders.append(path.name)
    assert offenders == []
