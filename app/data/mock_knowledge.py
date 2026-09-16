"""Mock/demo game knowledge.

The vertical slice models several quests across Majora's Mask areas, with
NPCs, schedules, timed events, mask and item requirements. Data is
deliberately NOT lore-complete: it exists to validate the architecture,
not the game.

``KnowledgeBase.retrieve`` is the seam where RAG (vector retrieval over a real
wiki dump) will plug in later.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.domain import ClockTime, GameState, Goal, TimeWindow

MASKS = [
    "Deku Mask",
    "Goron Mask",
    "Zora Mask",
    "Kafei's Mask",
    "Gibdo Mask",
    "All-Night Mask",
    "Blast Mask",
    "Stone Mask",
    "Great Fairy Mask",
    "Postman's Hat",
]


class Location(BaseModel):
    """A named place, grouped under an area such as Clock Town."""

    id: str
    name: str
    area: str


class NPC(BaseModel):
    """A character with a schedule: the windows they can be interacted with."""

    id: str
    name: str
    location: str
    schedule: list[TimeWindow] = Field(default_factory=list)

    def available_at(self, t: ClockTime) -> bool:
        """Check whether the NPC can be interacted with at a given time.

        args:
            t (ClockTime): the time to test.

        returns:
            bool: True when the time falls inside any schedule window.
        """
        return any(w.contains(t) for w in self.schedule)


class ScheduledEvent(BaseModel):
    """A timestamped in-world event that can gate or flavour an objective."""

    id: str
    name: str
    location: str
    window: TimeWindow
    description: str = ""


class Objective(BaseModel):
    """A single objective that can become one plan step."""

    id: str
    title: str
    description: str = ""
    location: str
    window: TimeWindow
    prerequisites: list[str] = Field(default_factory=list)
    requires_items: list[str] = Field(default_factory=list)
    requires_masks: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    npc_id: str = ""  # id of the NPC the player must interact with, if any
    event_ref: str = ""  # id of the ScheduledEvent this objective tracks, if any


class Quest(BaseModel):
    """A quest is just a named collection of objectives."""

    id: str
    name: str
    objectives: list[Objective]


class KnowledgeBase(BaseModel):
    """Holds all game data and answers retrieval queries."""

    quests: list[Quest] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    npcs: list[NPC] = Field(default_factory=list)
    events: list[ScheduledEvent] = Field(default_factory=list)

    @property
    def all_objectives(self) -> list[Objective]:
        """Flatten every objective of every quest into one list.

        args:
            (none)

        returns:
            list[Objective]: all objectives in quest order.
        """
        return [o for quest in self.quests for o in quest.objectives]

    def npc(self, npc_id: str) -> NPC | None:
        """Look up an NPC by id.

        args:
            npc_id (str): the NPC's identifier.

        returns:
            NPC | None: the matching NPC, or None when unknown.
        """
        return next((n for n in self.npcs if n.id == npc_id), None)

    def event(self, event_id: str) -> ScheduledEvent | None:
        """Look up a scheduled event by id.

        args:
            event_id (str): the event's identifier.

        returns:
            ScheduledEvent | None: the matching event, or None when unknown.
        """
        return next((e for e in self.events if e.id == event_id), None)

    def retrieve(self, game_state: GameState, goal: Goal) -> list[Objective]:
        """Return unfinished objectives matching the goal's keywords, best first.

        No keyword match means no relevant objective: an empty list tells the
        planner there is nothing grounded to work from, instead of leaking
        unrelated objectives from the whole knowledge slice.
        """
        done_quests = {qid for qid, status in game_state.quest_progress.items() if status == "done"}
        words = set(re.findall(r"[a-z']+", goal.description.lower()))
        scored: list[tuple[int, Objective]] = []
        for obj in self.all_objectives:
            if any(o in done_quests for o in _containing_quests(self.quests, obj.id)):
                continue
            score = len(words & set(obj.keywords))
            if score > 0:
                scored.append((score, obj))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [obj for _, obj in scored]


def _containing_quests(quests: list[Quest], objective_id: str) -> list[str]:
    """List the quest ids that contain a given objective.

    args:
        quests (list[Quest]): all quests to scan.
        objective_id (str): the objective's identifier.

    returns:
        list[str]: ids of quests owning that objective.
    """
    return [q.id for q in quests if any(o.id == objective_id for o in q.objectives)]


def _tw(day: int, start: tuple[int, int], end: tuple[int, int]) -> TimeWindow:
    """Helper to build a TimeWindow from (hour, minute) pairs."""
    sh, sm = start
    eh, em = end
    return TimeWindow(
        start=ClockTime(day=day, hour=sh, minute=sm), end=ClockTime(day=day, hour=eh, minute=em)
    )


def build_default_knowledge() -> KnowledgeBase:
    """Expanded game data: multiple areas, quests, NPCs and events."""
    # ── Locations ────────────────────────────────────────────────────
    locations = [
        # Clock Town
        Location(id="stockpot_inn", name="Stockpot Inn", area="West Clock Town"),
        Location(id="curiosity_shop", name="Curiosity Shop", area="South Clock Town"),
        Location(id="market_district", name="Market District", area="East Clock Town"),
        Location(id="post_office", name="Post Office", area="West Clock Town"),
        Location(id="south_clock_town", name="South Clock Town", area="Clock Town"),
        Location(id="north_clock_town", name="North Clock Town", area="Clock Town"),
        # Southern Swamp
        Location(id="swamp_spider_house", name="Swamp Spider House", area="Southern Swamp"),
        Location(id="dekupalace", name="Deku Palace", area="Southern Swamp"),
        Location(id="woodfall", name="Woodfall", area="Southern Swamp"),
        # Mountain Village
        Location(id="goron_shrine", name="Goron Shrine", area="Mountain Village"),
        Location(id="snowhead", name="Snowhead", area="Mountain Village"),
        # Great Bay
        Location(id="zora_hall", name="Zora Hall", area="Great Bay"),
        Location(id="pinnacle_rock", name="Pinnacle Rock", area="Great Bay"),
        Location(id="great_bay_coast", name="Great Bay Coast", area="Great Bay"),
        # Ikana Canyon
        Location(id="canyon_shrine", name="Canyon Shrine", area="Ikana Canyon"),
        Location(id="ancient_castle_ikana", name="Ancient Castle of Ikana", area="Ikana Canyon"),
        # Romani Ranch
        Location(id="ranch_house", name="Ranch House", area="Romani Ranch"),
        # Hub
        Location(id="termina_field", name="Termina Field", area="Termina"),
    ]
    # ── NPCs ─────────────────────────────────────────────────────────
    npcs = [
        # Clock Town
        NPC(
            id="anju",
            name="Anju",
            location="Stockpot Inn",
            schedule=[_tw(1, (8, 0), (21, 0)), _tw(2, (8, 0), (21, 0)), _tw(3, (8, 0), (23, 59))],
        ),
        NPC(
            id="kafei",
            name="Kafei",
            location="Curiosity Shop",
            schedule=[_tw(2, (12, 0), (23, 59)), _tw(3, (6, 0), (12, 0))],
        ),
        NPC(
            id="postman",
            name="Postman",
            location="Market District",
            schedule=[_tw(2, (9, 0), (17, 0))],
        ),
        NPC(
            id="bombers_leader",
            name="Bombers' Leader",
            location="North Clock Town",
            schedule=[_tw(1, (6, 0), (20, 0))],
        ),
        # Mountain Village
        NPC(
            id="goron_elder",
            name="Goron Elder",
            location="Goron Shrine",
            schedule=[
                _tw(1, (6, 0), (22, 0)),
                _tw(2, (6, 0), (22, 0)),
                _tw(3, (6, 0), (22, 0)),
            ],
        ),
        NPC(
            id="darmani",
            name="Darmani",
            location="Goron Shrine",
            schedule=[
                _tw(1, (22, 0), (23, 59)),
                _tw(2, (22, 0), (23, 59)),
                _tw(3, (22, 0), (23, 59)),
            ],
        ),
        # Great Bay
        NPC(
            id="mikau",
            name="Mikau",
            location="Great Bay Coast",
            schedule=[
                _tw(1, (6, 0), (23, 59)),
                _tw(2, (6, 0), (23, 59)),
                _tw(3, (6, 0), (23, 59)),
            ],
        ),
        NPC(
            id="tael",
            name="Tael",
            location="Zora Hall",
            schedule=[_tw(1, (18, 0), (23, 59)), _tw(2, (18, 0), (23, 59))],
        ),
        # Southern Swamp
        NPC(
            id="dekuboss",
            name="Deku King",
            location="Deku Palace",
            schedule=[
                _tw(1, (6, 0), (23, 59)),
                _tw(2, (6, 0), (23, 59)),
                _tw(3, (6, 0), (23, 59)),
            ],
        ),
        # Romani Ranch
        NPC(
            id="romani",
            name="Romani",
            location="Ranch House",
            schedule=[_tw(1, (6, 0), (20, 0)), _tw(2, (6, 0), (20, 0))],
        ),
        NPC(
            id="cremia",
            name="Cremia",
            location="Ranch House",
            schedule=[_tw(2, (20, 0), (23, 59))],
        ),
        # Ikana Canyon
        NPC(
            id="pamela",
            name="Pamela",
            location="Ancient Castle of Ikana",
            schedule=[_tw(2, (0, 0), (4, 0)), _tw(3, (0, 0), (4, 0))],
        ),
        NPC(
            id="shiro",
            name="Shiro",
            location="Canyon Shrine",
            schedule=[_tw(2, (22, 0), (23, 59)), _tw(3, (22, 0), (23, 59))],
        ),
    ]
    # ── Events ───────────────────────────────────────────────────────
    events = [
        # Clock Town — Anju & Kafei
        ScheduledEvent(
            id="ak_letter_delivery",
            name="Kafei's letter is delivered",
            location="Market District",
            window=_tw(2, (9, 0), (17, 0)),
        ),
        ScheduledEvent(
            id="ak_reunion_dinner",
            name="Anju and Kafei reunite",
            location="Stockpot Inn",
            window=_tw(3, (22, 0), (23, 59)),
        ),
        # Clock Town — Bombers
        ScheduledEvent(
            id="bm_hideout_gathering",
            name="Bombers gather at the hideout",
            location="South Clock Town",
            window=_tw(1, (8, 0), (22, 0)),
        ),
        # Romani Ranch
        ScheduledEvent(
            id="ranch_aliens",
            name="Romani defends the ranch from aliens",
            location="Ranch House",
            window=_tw(1, (2, 0), (4, 0)),
            description="Aliens attack the ranch at 2 AM on the First Night.",
        ),
        ScheduledEvent(
            id="ranch_milk_delivery",
            name="Cremia delivers milk to Clock Town",
            location="Market District",
            window=_tw(2, (20, 0), (23, 59)),
            description="Cremia's wagon ride through the canyon under moonlight.",
        ),
        # Ikana Canyon
        ScheduledEvent(
            id="ikana_piano",
            name="Ghost plays the piano in Ikana Castle",
            location="Ancient Castle of Ikana",
            window=_tw(3, (0, 0), (4, 0)),
        ),
        # Mountain Village
        ScheduledEvent(
            id="snowhead_blizzard",
            name="Blizzard rages near Snowhead",
            location="Snowhead",
            window=_tw(1, (0, 0), (23, 59)),
        ),
    ]
    # ── Quests ───────────────────────────────────────────────────────
    anju_kafei = Quest(
        id="anju_kafei",
        name="Anju and Kafei",
        objectives=[
            Objective(
                id="ak_talk_to_anju",
                title="Talk to Anju at the Stockpot Inn",
                description="Learn about her missing fiancé Kafei.",
                location="Stockpot Inn",
                window=_tw(2, (8, 0), (21, 0)),
                npc_id="anju",
                keywords=[
                    "anju",
                    "kafei",
                    "letter",
                    "reunite",
                    "start",
                    "parla",
                    "fidanzato",
                    "scomparso",
                    "locanda",
                ],
            ),
            Objective(
                id="ak_get_letter",
                title="Retrieve Kafei's letter from the mailbox",
                description="Kafei left a letter for you behind the Post Office.",
                location="Market District",
                window=_tw(2, (9, 0), (17, 0)),
                prerequisites=["ak_talk_to_anju"],
                npc_id="postman",
                event_ref="ak_letter_delivery",
                keywords=[
                    "kafei",
                    "letter",
                    "mailbox",
                    "post",
                    "cassetta",
                    "posta",
                    "postale",
                    "lettera",
                    "ufficio",
                ],
            ),
            Objective(
                id="ak_deliver_letter",
                title="Give the letter to Kafei at the Curiosity Shop",
                description="Kafei is hiding out in the Curiosity Shop basement.",
                location="Curiosity Shop",
                window=_tw(3, (6, 0), (12, 0)),
                prerequisites=["ak_get_letter"],
                requires_items=["Kafei's Letter"],
                npc_id="kafei",
                keywords=[
                    "kafei",
                    "letter",
                    "shop",
                    "hideout",
                    "consegna",
                    "cantina",
                    "nascondiglio",
                    "negozio",
                    "lettera",
                ],
            ),
            Objective(
                id="ak_reunite",
                title="Reunite Anju and Kafei at the Stockpot Inn",
                description="Bring everyone together before the dawn of the Third Day.",
                location="Stockpot Inn",
                window=_tw(3, (22, 0), (23, 59)),
                prerequisites=["ak_deliver_letter"],
                npc_id="anju",
                event_ref="ak_reunion_dinner",
                keywords=[
                    "anju",
                    "kafei",
                    "reunite",
                    "inn",
                    "riunisci",
                    "riunire",
                    "riunione",
                    "innamorati",
                    "coppia",
                    "terzo",
                    "giorno",
                    "locanda",
                ],
            ),
        ],
    )
    bombers = Quest(
        id="bombers",
        name="Bombers' Secret Society",
        objectives=[
            Objective(
                id="bm_talk_leader",
                title="Talk to the Bombers' leader in North Clock Town",
                description="The kid gang is suspicious of strangers.",
                location="North Clock Town",
                window=_tw(1, (6, 0), (20, 0)),
                npc_id="bombers_leader",
                keywords=[
                    "bombers",
                    "society",
                    "hideout",
                    "plan",
                    "leader",
                    "gang",
                    "ragazzini",
                    "società",
                    "nord",
                ],
            ),
            Objective(
                id="bm_find_hideout",
                title="Locate the hidden hideout behind the clock tower",
                description="The hideout entrance is marked by a odd drawing.",
                location="South Clock Town",
                window=_tw(1, (8, 0), (22, 0)),
                prerequisites=["bm_talk_leader"],
                requires_items=["Bomber's Notebook"],
                event_ref="bm_hideout_gathering",
                keywords=["hideout", "clock", "tower", "bombers", "tana", "orologio", "disegno"],
            ),
        ],
    )
    darmani_spirit = Quest(
        id="darmani_spirit",
        name="Darmani's Spirit",
        objectives=[
            Objective(
                id="dg_talk_elder",
                title="Listen to the Goron Elder's song",
                description="The Elder plays a melody that soothes Darmani's restless spirit.",
                location="Goron Shrine",
                window=_tw(1, (8, 0), (20, 0)),
                requires_masks=["Goron Mask"],
                npc_id="goron_elder",
                keywords=[
                    "darmani",
                    "goron",
                    "elder",
                    "song",
                    "spirit",
                    "ghost",
                    "montagna",
                    "canzone",
                    "spirito",
                ],
            ),
            Objective(
                id="dg_meet_darmani",
                title="Speak with Darmani's ghost at the Goron Shrine",
                description="Use the Lens of Truth to see Darmani's spirit.",
                location="Goron Shrine",
                window=_tw(1, (22, 0), (23, 59)),
                prerequisites=["dg_talk_elder"],
                requires_masks=["Goron Mask"],
                requires_items=["Lens of Truth"],
                npc_id="darmani",
                keywords=[
                    "darmani",
                    "ghost",
                    "spirit",
                    "lens",
                    "truth",
                    "see",
                    "fantasma",
                    "verità",
                    "lente",
                ],
            ),
            Objective(
                id="dg_learn_lullaby",
                title="Learn the Goron Lullaby from Darmani",
                description="Darmani teaches you the lullaby that will put the baby to sleep.",
                location="Goron Shrine",
                window=_tw(2, (22, 0), (23, 59)),
                prerequisites=["dg_meet_darmani"],
                requires_masks=["Goron Mask"],
                npc_id="darmani",
                keywords=[
                    "darmani",
                    "lullaby",
                    "baby",
                    "goron",
                    "ninna",
                    "canzone",
                    "nanna",
                    "bambino",
                ],
            ),
        ],
    )
    mikau_memory = Quest(
        id="mikau_memory",
        name="Mikau's Memory",
        objectives=[
            Objective(
                id="mm_find_tael",
                title="Ask Tael about Mikau at Zora Hall",
                description="Tael knows where Mikau's stolen eggs are hidden.",
                location="Zora Hall",
                window=_tw(1, (18, 0), (23, 59)),
                requires_masks=["Zora Mask"],
                npc_id="tael",
                keywords=[
                    "mikau",
                    "tael",
                    "zora",
                    "eggs",
                    "fish",
                    "stolen",
                    "uova",
                    "pesce",
                    "zora",
                    "hall",
                ],
            ),
            Objective(
                id="mm_recover_eggs",
                title="Retrieve Mikau's eggs from Pinnacle Rock",
                description="The Gerudo Pirates stole Mikau's eggs and hid them at Pinnacle Rock.",
                location="Pinnacle Rock",
                window=_tw(2, (6, 0), (18, 0)),
                prerequisites=["mm_find_tael"],
                requires_masks=["Zora Mask"],
                keywords=[
                    "mikau",
                    "eggs",
                    "pinnacle",
                    "rock",
                    "pirate",
                    "retrieve",
                    "uova",
                    "pirata",
                    "recupera",
                    "scogliera",
                ],
            ),
            Objective(
                id="mm_learn_song",
                title="Learn the Song of Opening from Mikau",
                description="Mikau teaches you the song that opens the Great Bay Temple.",
                location="Great Bay Coast",
                window=_tw(2, (18, 0), (23, 59)),
                prerequisites=["mm_recover_eggs"],
                requires_masks=["Zora Mask"],
                npc_id="mikau",
                keywords=[
                    "mikau",
                    "song",
                    "temple",
                    "great",
                    "bay",
                    "canzone",
                    "tempio",
                    "baia",
                ],
            ),
        ],
    )
    pamela_father = Quest(
        id="pamela_father",
        name="Pamela's Father",
        objectives=[
            Objective(
                id="pf_sneak_castle",
                title="Enter the Ancient Castle of Ikana at night",
                description="The castle is crawling with Gibdos during the night.",
                location="Ancient Castle of Ikana",
                window=_tw(2, (0, 0), (4, 0)),
                requires_masks=["Gibdo Mask"],
                keywords=[
                    "pamela",
                    "father",
                    "castle",
                    "gibdo",
                    "ikana",
                    "castle",
                    "notte",
                    "gibdo",
                    "castello",
                ],
            ),
            Objective(
                id="pf_free_father",
                title="Free Pamela's father from the Gibdo curse",
                description="Wearing the Gibdo Mask, play the Song of Healing to free him.",
                location="Ancient Castle of Ikana",
                window=_tw(2, (0, 0), (4, 0)),
                prerequisites=["pf_sneak_castle"],
                requires_masks=["Gibdo Mask"],
                keywords=[
                    "pamela",
                    "father",
                    "free",
                    "curse",
                    "healing",
                    "libera",
                    "maledizione",
                    "guarigione",
                ],
            ),
            Objective(
                id="pf_meet_pamela",
                title="Reunite with Pamela after freeing her father",
                description="Pamela is overjoyed to have her father back.",
                location="Ancient Castle of Ikana",
                window=_tw(3, (0, 0), (4, 0)),
                prerequisites=["pf_free_father"],
                requires_masks=["Gibdo Mask"],
                npc_id="pamela",
                keywords=[
                    "pamela",
                    "father",
                    "thank",
                    "freed",
                    "saved",
                    "padre",
                    "grazie",
                    "libero",
                ],
            ),
        ],
    )
    deku_princess = Quest(
        id="deku_princess",
        name="Deku Princess Rescue",
        objectives=[
            Objective(
                id="dp_talk_king",
                title="Plead with the Deku King for the princess",
                description="The Deku King believes you kidnapped his daughter.",
                location="Deku Palace",
                window=_tw(1, (8, 0), (20, 0)),
                requires_masks=["Deku Mask"],
                npc_id="dekuboss",
                keywords=[
                    "deku",
                    "princess",
                    "king",
                    "palace",
                    "rescue",
                    "deku",
                    "principessa",
                    "re",
                    "palazzo",
                ],
            ),
            Objective(
                id="dp_enter_woodfall",
                title="Navigate the swamp to reach Woodfall",
                description="Follow the trail through the Southern Swamp to Woodfall.",
                location="Woodfall",
                window=_tw(1, (8, 0), (23, 59)),
                prerequisites=["dp_talk_king"],
                requires_masks=["Deku Mask"],
                keywords=[
                    "woodfall",
                    "swamp",
                    "navigate",
                    "trail",
                    "palude",
                    "sentiero",
                    "woodfall",
                ],
            ),
            Objective(
                id="dp_free_princess",
                title="Free the Deku Princess from the monkey's cage",
                description="The monkey locked the princess in a cage at Woodfall.",
                location="Woodfall",
                window=_tw(2, (6, 0), (20, 0)),
                prerequisites=["dp_enter_woodfall"],
                requires_masks=["Deku Mask"],
                keywords=[
                    "deku",
                    "princess",
                    "monkey",
                    "cage",
                    "free",
                    "principesa",
                    "gabbia",
                    "libera",
                ],
            ),
        ],
    )
    romani_ranch = Quest(
        id="romani_ranch",
        name="Romani Ranch",
        objectives=[
            Objective(
                id="rr_help_romani",
                title="Help Romani practice shooting aliens at the ranch",
                description=(
                    "Romani needs your help defending the ranch from the Bremmmy Gyorgs tonight."
                ),
                location="Ranch House",
                window=_tw(1, (8, 0), (20, 0)),
                requires_items=["Powder Keg"],
                npc_id="romani",
                event_ref="ranch_aliens",
                keywords=[
                    "romani",
                    "ranch",
                    "aliens",
                    "shoot",
                    "practice",
                    "fattoria",
                    "alieni",
                    "tiro",
                ],
            ),
            Objective(
                id="rr_defend_ranch",
                title="Defend the ranch from the alien invasion",
                description="The aliens come at 2 AM. Use Cremia's wagon cannon to fight them off.",
                location="Ranch House",
                window=_tw(1, (2, 0), (4, 0)),
                prerequisites=["rr_help_romani"],
                requires_items=["Powder Keg"],
                event_ref="ranch_aliens",
                keywords=[
                    "aliens",
                    "defend",
                    "wagon",
                    "night",
                    "alieni",
                    "difendi",
                    "notte",
                    "carrozza",
                ],
            ),
            Objective(
                id="rr_milk_delivery",
                title="Ride with Cremia to deliver milk to Clock Town",
                description="Cremia needs an escort through the canyon on the Second Night.",
                location="Market District",
                window=_tw(2, (20, 0), (23, 59)),
                prerequisites=["rr_defend_ranch"],
                npc_id="cremia",
                event_ref="ranch_milk_delivery",
                keywords=[
                    "cremia",
                    "milk",
                    "delivery",
                    "escort",
                    "wagon",
                    "latticini",
                    "consegna",
                    "scorta",
                ],
            ),
        ],
    )
    deed_chain = Quest(
        id="deed_chain",
        name="Land Title Deed Chain",
        objectives=[
            Objective(
                id="dc_swamp_to_mountain",
                title="Deliver the Swamp Title Deed to the Goron Shrine",
                description="Trade the Swamp Title Deed for the Mountain Title Deed.",
                location="Goron Shrine",
                window=_tw(1, (8, 0), (20, 0)),
                requires_items=["Swamp Title Deed"],
                keywords=[
                    "deed",
                    "title",
                    "swamp",
                    "mountain",
                    "shrine",
                    "titolo",
                    "palude",
                    "montagna",
                    "scambio",
                ],
            ),
            Objective(
                id="dc_mountain_to_bay",
                title="Deliver the Mountain Title Deed to Zora Hall",
                description="Trade the Mountain Title Deed for the Ocean Title Deed.",
                location="Zora Hall",
                window=_tw(2, (6, 0), (18, 0)),
                prerequisites=["dc_swamp_to_mountain"],
                requires_items=["Mountain Title Deed"],
                keywords=[
                    "deed",
                    "title",
                    "mountain",
                    "ocean",
                    "zora",
                    "titolo",
                    "montagna",
                    "oceano",
                ],
            ),
            Objective(
                id="dc_bay_to_ikana",
                title="Deliver the Ocean Title Deed to Ikana Canyon",
                description="Trade the Ocean Title Deed for the Land Title Deed.",
                location="Canyon Shrine",
                window=_tw(2, (18, 0), (23, 59)),
                prerequisites=["dc_mountain_to_bay"],
                requires_items=["Ocean Title Deed"],
                keywords=[
                    "deed",
                    "title",
                    "ocean",
                    "land",
                    "ikana",
                    "titolo",
                    "oceano",
                    "terra",
                ],
            ),
            Objective(
                id="dc_land_to_ct",
                title="Deliver the Land Title Deed to Clock Town",
                description="Complete the cycle by returning the Land Title Deed.",
                location="Curiosity Shop",
                window=_tw(3, (8, 0), (18, 0)),
                prerequisites=["dc_bay_to_ikana"],
                requires_items=["Land Title Deed"],
                keywords=[
                    "deed",
                    "title",
                    "land",
                    "clock",
                    "town",
                    "titolo",
                    "terra",
                    "città",
                ],
            ),
        ],
    )
    return KnowledgeBase(
        quests=[
            anju_kafei,
            bombers,
            darmani_spirit,
            mikau_memory,
            pamela_father,
            deku_princess,
            romani_ranch,
            deed_chain,
        ],
        locations=locations,
        npcs=npcs,
        events=events,
    )
