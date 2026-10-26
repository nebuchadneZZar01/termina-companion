"""MCP tools: unit tests for each tool and an in-process Client integration."""

import asyncio

import pytest
from mcp import Client

from app.data.mock_knowledge import Objective
from app.mcp.server import mcp
from app.mcp.tools import (
    check_prerequisites,
    get_event,
    get_location,
    get_npc_schedule,
    get_objective,
    get_quest_info,
    search_quests,
)

# ---------------------------------------------------------------------------
# search_quests
# ---------------------------------------------------------------------------


def test_search_quests_finds_anju_kafei():
    """search_quests returns the full Anju & Kafei chain for a matching goal."""
    groups = search_quests("Reunite Anju and Kafei before the dawn of the Third Day")
    ids = [o["id"] for g in groups for o in g["objectives"]]
    assert set(ids) == {
        "ak_get_kafei_mask",
        "ak_get_room_key",
        "ak_talk_to_anju",
        "ak_meet_in_kitchen",
        "ak_post_letter",
        "ak_meet_kafei",
        "ak_deliver_pendant",
        "ak_sakon_hideout",
        "ak_reunite",
    }


def test_search_quests_empty_on_no_match():
    """search_quests returns an empty list for a goal with no matching keywords."""
    assert search_quests("completely unrelated phrase") == []


def test_search_quests_groups_by_quest():
    """Search results are grouped by quest."""
    groups = search_quests("Reunite Anju and Kafei")
    assert len(groups) == 1
    assert groups[0]["quest_id"] == "anju_kafei"
    assert groups[0]["quest_name"] == "Anju and Kafei"


def test_search_quests_excludes_done_quests():
    """Objectives of quests marked done are excluded from search results."""
    groups = search_quests(
        "Reunite Anju and Kafei",
        quest_progress={"anju_kafei": "done"},
    )
    assert groups == []


def test_search_quests_returns_valid_objective_dicts():
    """Objectives in the result round-trip through Objective.model_validate."""
    groups = search_quests("Goron Lullaby Darmani")
    for g in groups:
        for raw in g["objectives"]:
            obj = Objective.model_validate(raw)
            assert obj.id.startswith("dg_")


# ---------------------------------------------------------------------------
# get_npc_schedule
# ---------------------------------------------------------------------------


def test_get_npc_schedule_returns_windows():
    """get_npc_schedule returns readable slots and structured windows."""
    npc = get_npc_schedule("anju")
    assert npc["id"] == "anju"
    assert npc["name"] == "Anju"
    assert "schedule" in npc
    assert len(npc["schedule"]) >= 2
    assert all(isinstance(s, str) for s in npc["schedule"])
    assert len(npc["windows"]) == len(npc["schedule"])
    assert set(npc["windows"][0]) == {"start", "end"}
    assert set(npc["windows"][0]["start"]) == {"day", "hour", "minute"}


def test_get_npc_schedule_unknown_raises():
    """get_npc_schedule raises ValueError for an unknown NPC."""
    with pytest.raises(ValueError, match="Unknown NPC"):
        get_npc_schedule("nobody")


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_get_npc_schedule_missing_id_raises(bad):
    """get_npc_schedule rejects a missing/blank NPC id."""
    with pytest.raises(ValueError, match="Missing npc_id"):
        get_npc_schedule(bad)


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_get_event_missing_id_raises(bad):
    """get_event rejects a missing/blank event id."""
    with pytest.raises(ValueError, match="Missing event_id"):
        get_event(bad)


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_get_quest_info_missing_id_raises(bad):
    """get_quest_info rejects a missing/blank quest id."""
    with pytest.raises(ValueError, match="Missing quest_id"):
        get_quest_info(bad)


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_get_location_missing_id_raises(bad):
    """get_location rejects a missing/blank location id."""
    with pytest.raises(ValueError, match="Missing location_id"):
        get_location(bad)


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_check_prerequisites_missing_id_raises(bad):
    """check_prerequisites rejects a missing/blank objective id."""
    with pytest.raises(ValueError, match="Missing objective_id"):
        check_prerequisites(bad)


def test_tool_ids_are_stripped():
    """Surrounding whitespace in ids is normalized, not treated as unknown."""
    assert get_npc_schedule("  anju  ")["id"] == "anju"


# ---------------------------------------------------------------------------
# get_quest_info
# ---------------------------------------------------------------------------


def test_get_quest_info_returns_objectives():
    """get_quest_info returns the quest with its objectives."""
    info = get_quest_info("anju_kafei")
    assert info["id"] == "anju_kafei"
    assert info["name"] == "Anju and Kafei"
    assert len(info["objectives"]) == 9
    ids = {o["id"] for o in info["objectives"]}
    assert "ak_get_kafei_mask" in ids
    assert "ak_reunite" in ids


def test_get_quest_info_unknown_raises():
    with pytest.raises(ValueError, match="Unknown quest"):
        get_quest_info("no_such_quest")


# ---------------------------------------------------------------------------
# get_objective
# ---------------------------------------------------------------------------


def test_get_objective_returns_objective_and_quest():
    """get_objective resolves one objective and names the quest owning it."""
    info = get_objective("ak_reunite")
    assert info["id"] == "ak_reunite"
    assert info["quest_id"] == "anju_kafei"
    assert info["quest_name"] == "Anju and Kafei"
    assert info["objective"]["id"] == "ak_reunite"
    assert "window" in info["objective"]


def test_get_objective_unknown_raises():
    with pytest.raises(ValueError, match="Unknown objective"):
        get_objective("no_such_objective")


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_get_objective_missing_id_raises(bad):
    """get_objective rejects a missing/blank objective id."""
    with pytest.raises(ValueError, match="Missing objective_id"):
        get_objective(bad)


# ---------------------------------------------------------------------------
# get_event
# ---------------------------------------------------------------------------


def test_get_event_returns_details():
    event = get_event("ak_letter_delivery")
    assert event["name"] == "Kafei's letter is delivered"
    assert event["location"] == "Stockpot Inn"
    assert "Day" in event["window"]


def test_get_event_unknown_raises():
    with pytest.raises(ValueError, match="Unknown event"):
        get_event("no_event")


# ---------------------------------------------------------------------------
# get_location
# ---------------------------------------------------------------------------


def test_get_location_returns_area():
    loc = get_location("stockpot_inn")
    assert loc == {"id": "stockpot_inn", "name": "Stockpot Inn", "area": "West Clock Town"}


def test_get_location_unknown_raises():
    with pytest.raises(ValueError, match="Unknown location"):
        get_location("nowhere")


# ---------------------------------------------------------------------------
# check_prerequisites
# ---------------------------------------------------------------------------


def test_check_prerequisites_met():
    """Prerequisites are met when items/masks are owned and prereqs are done."""
    result = check_prerequisites(
        "ak_sakon_hideout",
        inventory=["Hookshot"],
        masks=["Garo's Mask"],
        quest_progress={"anju_kafei": "done"},
    )
    assert result["met"]
    assert result["missing_items"] == []
    assert result["missing_masks"] == []
    assert result["unmet_prerequisites"] == []


def test_check_prerequisites_missing_items():
    """Missing items are reported when the player lacks them."""
    result = check_prerequisites("ak_deliver_pendant", inventory=[])
    assert not result["met"]
    assert "Pendant of Memories" in result["missing_items"]


def test_check_prerequisites_missing_masks():
    """Missing masks are reported when the player lacks them."""
    result = check_prerequisites("ak_sakon_hideout", inventory=["Hookshot"])
    assert not result["met"]
    assert "Garo's Mask" in result["missing_masks"]


def test_check_prerequisites_unknown_raises():
    with pytest.raises(ValueError, match="Unknown objective"):
        check_prerequisites("nobody")


# ---------------------------------------------------------------------------
# MCP server in-process integration (tests the full protocol stack)
# ---------------------------------------------------------------------------


def _run_async(coro):
    """Run an async coroutine from a sync test (no pytest-asyncio needed)."""
    return asyncio.run(coro)


def test_mcp_server_lists_all_tools():
    """The MCP server exposes all 6 tools through the protocol."""

    async def _check():
        async with Client(mcp) as client:
            result = await client.list_tools()
            return [t.name for t in result.tools]

    tools = _run_async(_check())
    expected = {
        "search_quests",
        "get_npc_schedule",
        "get_quest_info",
        "get_event",
        "get_location",
        "check_prerequisites",
    }
    assert expected <= set(tools)


def test_mcp_server_search_via_client():
    """Calling search_quests through the in-process MCP client works end to end."""

    async def _call():
        async with Client(mcp) as client:
            return await client.call_tool(
                "search_quests",
                {"goal_text": "Reunite Anju and Kafei", "quest_progress": {}},
            )

    result = _run_async(_call())
    assert not result.is_error
    assert result.structured_content is not None
    groups = result.structured_content["result"]
    assert len(groups) == 1
    assert groups[0]["quest_id"] == "anju_kafei"
