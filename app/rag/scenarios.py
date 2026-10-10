"""Live calibration scenarios for RAG threshold tuning.

Each scenario is a realistic Knowledge Agent query (goal + objective titles +
keywords) paired with the Zelda Wiki pages the live wiki actually returns for
it. Page titles were discovered 2026-10-10 via per-scenario isolated retrieval
(open filter) and frozen here; they are matched case-insensitively by
``app.rag.evaluation``. Note ``mikau-eggs`` resolves to Zora's Domain pages:
a wiki-search relevance quirk, kept as-is so the set measures the threshold
filter rather than search quality.

Importing this module requires no network; running calibration does.
"""

from __future__ import annotations

from app.rag.evaluation import RetrievalScenario

CALIBRATED_THRESHOLD = 0.60
CALIBRATED_HIT = "7/14 @0.60 top_k=4 (0.72: 3/14, 0.80: 1/14)"
CALIBRATED_DATE = "2026-10-10"

CALIBRATION_SCENARIOS: list[RetrievalScenario] = [
    RetrievalScenario(
        id="anju-kafei-start",
        query="Reunite Anju and Kafei Talk to Anju at the Stockpot Inn anju kafei letter",
        expected_titles={"Anju and Kafei's Wedding", "Anju's Anguish"},
        search_terms=["Anju", "Kafei"],
        top_k=4,
    ),
    RetrievalScenario(
        id="anju-kafei-letter",
        query="Retrieve Kafei letter mailbox postman Kafei letter Market District",
        expected_titles={"Kafei", "Postman", "Postman's Hat"},
        search_terms=["Kafei", "Postman"],
        top_k=4,
    ),
    RetrievalScenario(
        id="bombers-notebook",
        query="Bombers Secret Society notebook leader North Clock Town bombers hideout",
        expected_titles={"Bombers' Notebook"},
        search_terms=["Bombers", "Notebook"],
        top_k=4,
    ),
    RetrievalScenario(
        id="darmani-song",
        query="Listen Goron Elder song Darmani spirit ghost Goron Shrine mountain",
        expected_titles={"Goron Mask", "Goron's Bracelet"},
        search_terms=["Darmani", "Goron"],
        top_k=4,
    ),
    RetrievalScenario(
        id="darmani-lullaby",
        query="Learn Goron Lullaby Darmani baby lullaby Goron Mask Lens of Truth",
        expected_titles={"Goron Mask", "Darmani III"},
        search_terms=["Darmani", "Goron Mask"],
        top_k=4,
    ),
    RetrievalScenario(
        id="mikau-eggs",
        query="Retrieve Mikau eggs Pinnacle Rock pirates Zora Hall stolen eggs",
        expected_titles={"Throne Room (Zora's Domain)", "Reach Zora's Domain"},
        search_terms=["Mikau", "Zora"],
        top_k=4,
    ),
    RetrievalScenario(
        id="mikau-song",
        query="Learn Song of Opening Mikau temple Great Bay Coast Zora Mask",
        expected_titles={"Mikau", "Mikau Lake", "Mikau's Diary"},
        search_terms=["Mikau", "Zora Hall"],
        top_k=4,
    ),
    RetrievalScenario(
        id="pamela-father",
        query="Free Pamela father Gibdo curse Ancient Castle of Ikana Gibdo Mask night",
        expected_titles={"Gibdo", "Pamela's Father", "Pamela"},
        search_terms=["Pamela", "Gibdo"],
        top_k=4,
    ),
    RetrievalScenario(
        id="pamela-castle",
        query="Enter Ancient Castle of Ikana night Gibdos Ikana Canyon castle",
        expected_titles={"Gibdo", "Ikana Graveyard"},
        search_terms=["Ikana", "Gibdo"],
        top_k=4,
    ),
    RetrievalScenario(
        id="deku-princess",
        query="Free Deku Princess monkey cage Woodfall swamp Deku Palace king",
        expected_titles={"Deku Princess"},
        search_terms=["Deku Princess", "Woodfall"],
        top_k=4,
    ),
    RetrievalScenario(
        id="deku-swamp",
        query="Navigate swamp reach Woodfall Southern Swamp trail Deku Mask",
        expected_titles={"Swamp, 4: Woodfall", "Woodfall Temple", "Woodfall"},
        search_terms=["Woodfall", "Swamp"],
        top_k=4,
    ),
    RetrievalScenario(
        id="romani-aliens",
        query="Defend ranch alien invasion Romani Ranch aliens night Powder Keg",
        expected_titles={"Romani", "Romani Ranch", "Helping Romani and Cremia"},
        search_terms=["Romani", "Aliens"],
        top_k=4,
    ),
    RetrievalScenario(
        id="romani-milk",
        query="Ride Cremia deliver milk Clock Town wagon canyon Second Night",
        expected_titles={"Helping Romani and Cremia", "Romani", "Cremia"},
        search_terms=["Cremia", "Romani"],
        top_k=4,
    ),
    RetrievalScenario(
        id="deed-chain",
        query="Deliver Swamp Title Deed Goron Shrine trade Mountain Title Deed",
        expected_titles={"Swamp Title Deed", "Swamp Palace", "Midoro Swamp"},
        search_terms=["Title Deed", "Swamp"],
        top_k=4,
    ),
]
