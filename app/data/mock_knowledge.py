"""Mock/demo game knowledge.

The vertical slice models several quests across Majora's Mask areas, with
NPCs, schedules, timed events, mask and item requirements. Data is
deliberately NOT lore-complete: it exists to validate the architecture,
not the game.

Agents read this data through the MCP tools in ``app.mcp.tools``, never
directly.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain import ClockTime, TimeWindow

MASKS = [
    "Deku Mask",
    "Goron Mask",
    "Zora Mask",
    "Kafei's Mask",
    "Garo's Mask",
    "Couple's Mask",
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
    provides_items: list[str] = Field(default_factory=list)
    provides_masks: list[str] = Field(default_factory=list)
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


def _tw(day: int, start: tuple[int, int], end: tuple[int, int]) -> TimeWindow:
    """Build a TimeWindow on one game day from (hour, minute) pairs."""
    sh, sm = start
    eh, em = end
    return TimeWindow(
        start=ClockTime(day=day, hour=sh, minute=sm), end=ClockTime(day=day, hour=eh, minute=em)
    )


def _tw_span(
    start_day: int,
    start: tuple[int, int],
    end_day: int,
    end: tuple[int, int],
) -> TimeWindow:
    """Build a TimeWindow that may cross the 06:00 game-day boundary."""
    sh, sm = start
    eh, em = end
    return TimeWindow(
        start=ClockTime(day=start_day, hour=sh, minute=sm),
        end=ClockTime(day=end_day, hour=eh, minute=em),
    )


def build_default_knowledge() -> KnowledgeBase:
    """Expanded game data: multiple areas, quests, NPCs and events."""
    # ── Locations ────────────────────────────────────────────────────
    locations = [
        # Clock Town
        Location(id="stockpot_inn", name="Stockpot Inn", area="West Clock Town"),
        Location(id="curiosity_shop", name="Curiosity Shop", area="South Clock Town"),
        Location(id="market_district", name="Market District", area="East Clock Town"),
        Location(id="mayor_residence", name="Mayor's Residence", area="East Clock Town"),
        Location(id="post_office", name="Post Office", area="West Clock Town"),
        Location(id="laundry_pool", name="Laundry Pool", area="South Clock Town"),
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
        Location(id="sakons_hideout", name="Sakon's Hideout", area="Ikana Canyon"),
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
            schedule=[
                _tw(1, (8, 0), (21, 5)),
                _tw(1, (23, 30), (29, 0)),
                _tw(2, (8, 0), (21, 5)),
                _tw(3, (8, 0), (18, 0)),
                _tw(3, (28, 0), (29, 0)),
            ],
        ),
        NPC(
            id="kafei",
            name="Kafei",
            location="Curiosity Shop",
            schedule=[
                _tw_span(2, (15, 0), 3, (13, 0)),
                _tw(3, (18, 0), (27, 0)),
            ],
        ),
        NPC(
            id="postman",
            name="Postman",
            location="Market District",
            schedule=[_tw(1, (9, 0), (17, 0)), _tw(2, (9, 0), (17, 0))],
        ),
        NPC(
            id="madame_aroma",
            name="Madame Aroma",
            location="Mayor's Residence",
            schedule=[_tw(1, (10, 0), (20, 0)), _tw(2, (10, 0), (20, 0))],
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
            schedule=[_tw(1, (24, 0), (28, 0)), _tw(2, (24, 0), (28, 0))],
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
            window=_tw(1, (14, 10), (14, 30)),
        ),
        ScheduledEvent(
            id="ak_pendant_delivery",
            name="Pendant of Memories reaches Anju",
            location="Stockpot Inn",
            window=_tw(2, (15, 0), (15, 30)),
        ),
        ScheduledEvent(
            id="ak_sakon_arrival",
            name="Sakon returns to his hideout",
            location="Sakon's Hideout",
            window=_tw(3, (18, 0), (18, 30)),
        ),
        ScheduledEvent(
            id="ak_reunion_dinner",
            name="Anju and Kafei reunite",
            location="Stockpot Inn",
            window=_tw(3, (28, 30), (29, 0)),
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
            window=_tw(1, (26, 0), (28, 0)),
            description="Aliens attack the ranch at 2 AM at the end of the First Day.",
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
            window=_tw(2, (24, 0), (28, 0)),
        ),
        # Mountain Village
        ScheduledEvent(
            id="snowhead_blizzard",
            name="Blizzard rages near Snowhead",
            location="Snowhead",
            window=_tw(1, (6, 0), (23, 59)),
        ),
    ]
    # ── Quests ───────────────────────────────────────────────────────
    anju_kafei = Quest(
        id="anju_kafei",
        name="Anju and Kafei",
        objectives=[
            Objective(
                id="ak_get_kafei_mask",
                title="Get Kafei's Mask from Madame Aroma",
                description="Madame Aroma gives you Kafei's Mask at the Mayor's Residence.",
                location="Mayor's Residence",
                window=_tw(1, (10, 0), (20, 0)),
                provides_masks=["Kafei's Mask"],
                npc_id="madame_aroma",
                keywords=[
                    "anju",
                    "kafei",
                    "mask",
                    "madame",
                    "aroma",
                    "mayor",
                    "residence",
                    "maschera",
                    "sindaco",
                    "residenza",
                ],
            ),
            Objective(
                id="ak_get_room_key",
                title="Get the Stockpot Inn room key from Anju",
                description="Anju lends you the key to her room at the Stockpot Inn.",
                location="Stockpot Inn",
                window=_tw(1, (13, 50), (16, 10)),
                prerequisites=["ak_get_kafei_mask"],
                provides_items=["Room Key"],
                npc_id="anju",
                keywords=[
                    "anju",
                    "kafei",
                    "room",
                    "key",
                    "stockpot",
                    "inn",
                    "camera",
                    "chiave",
                    "locanda",
                ],
            ),
            Objective(
                id="ak_talk_to_anju",
                title="Talk to Anju at the Stockpot Inn",
                description="Show Kafei's Mask to Anju after Kafei's letter arrives.",
                location="Stockpot Inn",
                window=_tw(1, (14, 20), (21, 5)),
                prerequisites=["ak_get_room_key"],
                requires_masks=["Kafei's Mask"],
                npc_id="anju",
                event_ref="ak_letter_delivery",
                keywords=[
                    "anju",
                    "kafei",
                    "talk",
                    "letter",
                    "stockpot",
                    "inn",
                    "parla",
                    "lettera",
                    "locanda",
                ],
            ),
            Objective(
                id="ak_meet_in_kitchen",
                title="Meet Anju in the Stockpot Inn kitchen",
                description="Anju gives you a letter for Kafei during the night.",
                location="Stockpot Inn",
                window=_tw(1, (23, 30), (29, 0)),
                prerequisites=["ak_talk_to_anju"],
                requires_items=["Room Key"],
                provides_items=["Letter to Kafei"],
                npc_id="anju",
                keywords=[
                    "anju",
                    "kafei",
                    "letter",
                    "kitchen",
                    "night",
                    "cucina",
                    "notte",
                    "lettera",
                    "locanda",
                ],
            ),
            Objective(
                id="ak_post_letter",
                title="Post the letter to Kafei in the Laundry Pool",
                description="Drop the Letter to Kafei in the mailbox so it reaches him at dawn.",
                location="Laundry Pool",
                window=_tw_span(1, (24, 0), 2, (6, 0)),
                prerequisites=["ak_meet_in_kitchen"],
                requires_items=["Letter to Kafei"],
                keywords=[
                    "anju",
                    "kafei",
                    "letter",
                    "post",
                    "mailbox",
                    "laundry",
                    "pool",
                    "lettera",
                    "posta",
                    "buca",
                    "lavatoio",
                ],
            ),
            Objective(
                id="ak_meet_kafei",
                title="Meet Kafei in the Curiosity Shop back room",
                description="Kafei gives you the Pendant of Memories for Anju.",
                location="Curiosity Shop",
                window=_tw_span(2, (15, 0), 3, (13, 0)),
                prerequisites=["ak_post_letter"],
                provides_items=["Pendant of Memories"],
                npc_id="kafei",
                keywords=[
                    "anju",
                    "kafei",
                    "pendant",
                    "curiosity",
                    "shop",
                    "hideout",
                    "ciondolo",
                    "negozio",
                    "nascondiglio",
                ],
            ),
            Objective(
                id="ak_deliver_pendant",
                title="Deliver the Pendant of Memories to Anju",
                description="Bring Kafei's pendant back to Anju at the Stockpot Inn.",
                location="Stockpot Inn",
                window=_tw(2, (15, 0), (21, 0)),
                prerequisites=["ak_meet_kafei"],
                requires_items=["Pendant of Memories"],
                npc_id="anju",
                event_ref="ak_pendant_delivery",
                keywords=[
                    "anju",
                    "kafei",
                    "pendant",
                    "deliver",
                    "stockpot",
                    "inn",
                    "ciondolo",
                    "consegna",
                    "locanda",
                ],
            ),
            Objective(
                id="ak_sakon_hideout",
                title="Enter Sakon's Hideout and recover the Sun's Mask",
                description=(
                    "Use the Garo's Mask and Hookshot to help Kafei reclaim the Sun's Mask."
                ),
                location="Sakon's Hideout",
                window=_tw(3, (18, 0), (27, 0)),
                prerequisites=["ak_deliver_pendant"],
                requires_masks=["Garo's Mask"],
                requires_items=["Hookshot"],
                provides_items=["Sun's Mask"],
                npc_id="kafei",
                event_ref="ak_sakon_arrival",
                keywords=[
                    "anju",
                    "kafei",
                    "sakon",
                    "hideout",
                    "garo",
                    "hookshot",
                    "sun",
                    "mask",
                    "nascondiglio",
                    "sole",
                    "maschera",
                ],
            ),
            Objective(
                id="ak_reunite",
                title="Reunite Anju and Kafei at the Stockpot Inn",
                description=(
                    "Bring the couple together before the moon falls and receive the Couple's Mask."
                ),
                location="Stockpot Inn",
                window=_tw(3, (28, 0), (29, 0)),
                prerequisites=["ak_sakon_hideout"],
                provides_masks=["Couple's Mask"],
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
                    "mattina",
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
                id="bm_pop_balloon",
                title="Pop the Majora Balloon in North Clock Town and talk to Jim",
                description=(
                    "Use a Deku Bubble (or other means) to pop the balloon Jim is shooting at. "
                    "He challenges Link to a game of hide-and-seek."
                ),
                location="North Clock Town",
                window=_tw(1, (6, 0), (20, 0)),
                npc_id="bombers_leader",
                keywords=[
                    "bombers",
                    "balloon",
                    "majora",
                    "jim",
                    "deku",
                    "bubble",
                    "leader",
                    "palloncino",
                ],
            ),
            Objective(
                id="bm_hide_and_seek",
                title="Find all five Bombers in hide-and-seek",
                description=(
                    "Locate and catch all five Bombers scattered around Clock Town within "
                    "the time limit to prove yourself to the gang."
                ),
                location="North Clock Town",
                window=_tw(1, (6, 0), (21, 0)),
                prerequisites=["bm_pop_balloon"],
                npc_id="bombers_leader",
                keywords=[
                    "bombers",
                    "hide",
                    "seek",
                    "nascondino",
                    "gang",
                    "find",
                    "catch",
                ],
            ),
            Objective(
                id="bm_get_notebook",
                title="Obtain the Bombers' Notebook",
                description=(
                    "After completing hide-and-seek (or by using the code to enter and exit "
                    "the hideout), receive the Bombers' Notebook from Jim. The notebook "
                    "tracks side quests throughout Termina."
                ),
                location="North Clock Town",
                window=_tw(1, (6, 0), (22, 0)),
                prerequisites=["bm_hide_and_seek"],
                provides_items=["Bomber's Notebook"],
                npc_id="bombers_leader",
                keywords=[
                    "bombers",
                    "notebook",
                    "taccuino",
                    "jim",
                    "member",
                    "code",
                    "password",
                ],
            ),
            Objective(
                id="bm_enter_hideout",
                title="Enter the Bombers' Hideout using the secret code",
                description=(
                    "Use the Bombers' secret code at the hideout entrance in East Clock Town "
                    "(sewer leading to the Astral Observatory area) to gain access."
                ),
                location="East Clock Town",
                window=_tw(1, (6, 0), (23, 0)),
                prerequisites=["bm_get_notebook"],
                requires_items=["Bomber's Notebook"],
                event_ref="bm_hideout_gathering",
                keywords=[
                    "hideout",
                    "code",
                    "password",
                    "sewer",
                    "east",
                    "astral",
                    "observatory",
                    "tana",
                    "codice",
                ],
            ),
        ],
    )
    darmani_spirit = Quest(
        id="darmani_spirit",
        name="Darmani's Spirit",
        objectives=[
            Objective(
                id="dg_talk_elder",
                title="Talk to the Goron Elder about Darmani",
                description="The Goron Elder tells Link about Darmani, the fallen Goron hero of Snowhead.",
                location="Goron Shrine",
                window=_tw(1, (6, 0), (21, 0)),
                npc_id="goron_elder",
                keywords=[
                    "elder",
                    "goron",
                    "darmani",
                    "snowhead",
                    "anziano",
                    "hero",
                    "eroe",
                    "spirito",
                ],
            ),
            Objective(
                id="dg_get_lens",
                title="Obtain the Lens of Truth from the Curiosity Shop",
                description="Purchase the Lens of Truth to see things that are invisible to the naked eye.",
                location="Curiosity Shop",
                window=_tw(1, (6, 0), (21, 0)),
                provides_items=["Lens of Truth"],
                keywords=[
                    "lens",
                    "truth",
                    "curiosity",
                    "shop",
                    "negozio",
                    "curiosità",
                    "lente",
                    "verità",
                ],
            ),
            Objective(
                id="dg_see_darmani",
                title="See Darmani's spirit with the Lens of Truth",
                description=(
                    "At night in the Goron Shrine, use the Lens of Truth to see Darmani's spirit. "
                    "Speak to him to learn the Goron Lullaby."
                ),
                location="Goron Shrine",
                window=_tw(1, (22, 0), (29, 0)),
                prerequisites=["dg_talk_elder", "dg_get_lens"],
                requires_items=["Lens of Truth"],
                npc_id="darmani",
                keywords=[
                    "darmani",
                    "ghost",
                    "fantasma",
                    "lens",
                    "spirito",
                    "shrine",
                    "santuario",
                    "goron",
                    "lullaby",
                    "ninna",
                    "nanna",
                ],
            ),
            Objective(
                id="dg_heal_darmani",
                title="Heal Darmani's spirit with the Song of Healing",
                description=(
                    "Play the Song of Healing for Darmani's spirit to soothe him. "
                    "In return, he grants you the Goron Mask."
                ),
                location="Goron Shrine",
                window=_tw(1, (22, 0), (29, 0)),
                prerequisites=["dg_see_darmani"],
                provides_masks=["Goron Mask"],
                npc_id="darmani",
                event_ref="darmani_healing",
                keywords=[
                    "darmani",
                    "healing",
                    "song",
                    "goron",
                    "mask",
                    "maschera",
                    "guarigione",
                    "canzone",
                ],
            ),
        ],
    )
    mikau_memory = Quest(
        id="mikau_memory",
        name="Mikau's Memory",
        objectives=[
            Objective(
                id="mm_heal_mikau",
                title="Heal Mikau's spirit with the Song of Healing",
                description=(
                    "Find Mikau's spirit washed up on Great Bay Coast and play the Song of Healing "
                    "to soothe him. In return, he grants you the Zora Mask."
                ),
                location="Great Bay Coast",
                window=_tw(1, (6, 0), (23, 59)),
                npc_id="mikau",
                provides_masks=["Zora Mask"],
                event_ref="mikau_healing",
                keywords=[
                    "zora",
                    "mask",
                    "mikau",
                    "healing",
                    "song",
                    "coast",
                    "spiaggia",
                    "maschera",
                    "guarigione",
                ],
            ),
            Objective(
                id="mm_talk_band",
                title="Talk to the Indigo-Go's about Lulu's stolen eggs",
                description=(
                    "In Zora form, speak to the members of the Indigo-Go's at Zora Hall. "
                    "They reveal that Lulu's eggs were stolen by Gerudo Pirates and hidden at Pinnacle Rock."
                ),
                location="Zora Hall",
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["mm_heal_mikau"],
                npc_id="indigo_gos",
                keywords=[
                    "indigo",
                    "go's",
                    "zora",
                    "hall",
                    "eggs",
                    "lulu",
                    "pirates",
                    "gerudo",
                    "uova",
                    "band",
                ],
            ),
            Objective(
                id="mm_recover_eggs",
                title="Retrieve Lulu's eggs from Pinnacle Rock",
                description=(
                    "Swim through the underwater tunnels of Pinnacle Rock in Zora form and "
                    "recover all of Lulu's stolen eggs from the Gerudo Pirates."
                ),
                location="Pinnacle Rock",
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["mm_talk_band"],
                keywords=[
                    "eggs",
                    "pirates",
                    "pinnacle",
                    "rock",
                    "uova",
                    "pirati",
                    "gerudo",
                    "underwater",
                ],
            ),
            Objective(
                id="mm_learn_bossa_nova",
                title="Return the eggs and learn the New Wave Bossa Nova",
                description=(
                    "Bring Lulu's eggs back to Zora Hall. The Indigo-Go's will perform and "
                    "Mikau will teach Link the New Wave Bossa Nova to open Great Bay Temple."
                ),
                location="Zora Hall",
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["mm_recover_eggs"],
                npc_id="mikau",
                keywords=[
                    "bossa",
                    "nova",
                    "song",
                    "mikau",
                    "temple",
                    "eggs",
                    "lulu",
                    "canzone",
                    "tempio",
                ],
            ),
        ],
    )

    pamela_father = Quest(
        id="pamela_father",
        name="Pamela's Father",
        objectives=[
            Objective(
                id="pf_find_pamela",
                title="Find Pamela and her cursed father at the Music Box House",
                description=(
                    "Travel to Ikana Canyon and visit the Music Box House. "
                    "There you find Pamela and her father, cursed into the form of a Gibdo."
                ),
                location="Music Box House",
                window=_tw(1, (6, 0), (23, 59)),
                npc_id="pamela",
                keywords=[
                    "pamela",
                    "father",
                    "gibdo",
                    "ikana",
                    "music",
                    "box",
                    "house",
                    "cursed",
                ],
            ),
            Objective(
                id="pf_get_gibdo_mask",
                title="Obtain the Gibdo Mask in the Ancient Castle of Ikana",
                description=(
                    "Explore the Ancient Castle of Ikana and its well. Use the Elegy of Emptiness "
                    "to create statues and progress. Play the Song of Healing to a Gibdo to obtain the Gibdo Mask."
                ),
                location="Ancient Castle of Ikana",
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["pf_find_pamela"],
                provides_masks=["Gibdo Mask"],
                keywords=[
                    "gibdo",
                    "mask",
                    "castle",
                    "ikana",
                    "elegy",
                    "well",
                    "maschera",
                ],
            ),
            Objective(
                id="pf_free_father",
                title="Free Pamela's father with the Gibdo Mask and Song of Healing",
                description=(
                    "Return to the Music Box House wearing the Gibdo Mask so Pamela's father "
                    "will not attack. Play the Song of Healing to break the curse and restore him."
                ),
                location="Music Box House",
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["pf_get_gibdo_mask"],
                requires_masks=["Gibdo Mask"],
                npc_id="pamela",
                event_ref="pamela_father_heal",
                keywords=[
                    "pamela",
                    "father",
                    "gibdo",
                    "mask",
                    "healing",
                    "song",
                    "liberare",
                    "guarigione",
                ],
            ),
            Objective(
                id="pf_reunite_pamela",
                title="Reunite Pamela with her father",
                description="Pamela is overjoyed to be reunited with her father after breaking his curse.",
                location="Music Box House",
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["pf_free_father"],
                npc_id="pamela",
                keywords=[
                    "pamela",
                    "father",
                    "riunione",
                    "ikana",
                    "happy",
                    "back",
                ],
            ),
        ],
    )

    deku_princess = Quest(
        id="deku_princess",
        name="Deku Princess Rescue",
        objectives=[
            Objective(
                id="dp_get_deku_mask",
                title="Obtain the Deku Mask from the Happy Mask Salesman",
                description=(
                    "After retrieving the Ocarina of Time and turning back time with the Song of Time, "
                    "learn the Song of Healing from the Happy Mask Salesman to receive the Deku Mask."
                ),
                location="Clock Tower",
                window=_tw(1, (6, 0), (23, 59)),
                provides_masks=["Deku Mask"],
                npc_id="mask_salesman",
                event_ref="deku_mask_healing",
                keywords=[
                    "deku",
                    "mask",
                    "salesman",
                    "healing",
                    "song",
                    "maschera",
                    "venditore",
                ],
            ),
            Objective(
                id="dp_talk_king",
                title="Speak to the Deku King at Deku Palace",
                description=(
                    "Enter Deku Palace in Deku form and speak to the Deku King. "
                    "He blames you for the disappearance of the Deku Princess."
                ),
                location="Deku Palace",
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dp_get_deku_mask"],
                requires_masks=["Deku Mask"],
                npc_id="dekuboss",
                keywords=[
                    "deku",
                    "princess",
                    "king",
                    "palace",
                    "rescue",
                    "principessa",
                    "re",
                    "palazzo",
                ],
            ),
            Objective(
                id="dp_enter_woodfall",
                title="Head to Woodfall Temple through Southern Swamp",
                description=(
                    "Navigate Southern Swamp, rescue Koume if needed, and make your way to "
                    "Woodfall Temple to find the source of the poison."
                ),
                location="Woodfall",
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dp_talk_king"],
                keywords=[
                    "woodfall",
                    "swamp",
                    "temple",
                    "palude",
                    "temple",
                ],
            ),
            Objective(
                id="dp_defeat_odolwa",
                title="Defeat Odolwa and rescue the Deku Princess",
                description=(
                    "Clear Woodfall Temple and defeat Odolwa. Rescue the Deku Princess, "
                    "capture her in an Empty Bottle, and return her to the Deku King."
                ),
                location="Woodfall Temple",
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dp_enter_woodfall"],
                requires_items=["Empty Bottle"],
                npc_id="dekup",
                event_ref="deku_princess_rescue",
                keywords=[
                    "odolwa",
                    "princess",
                    "bottle",
                    "temple",
                    "rescue",
                    "principessa",
                    "ampolla",
                ],
            ),
            Objective(
                id="dp_butler_race",
                title="Race the Deku Butler for the Mask of Scents",
                description=(
                    "After returning the Deku Princess to the Deku King, race the Deku Butler "
                    "through the Deku Shrine to earn the Mask of Scents."
                ),
                location="Deku Shrine",
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dp_defeat_odolwa"],
                provides_masks=["Mask of Scents"],
                npc_id="deku_butler",
                keywords=[
                    "butler",
                    "race",
                    "mask",
                    "scents",
                    "shrine",
                    "gara",
                    "maschera",
                ],
            ),
        ],
    )

    romani_ranch = Quest(
        id="romani_ranch",
        name="Romani Ranch",
        objectives=[
            Objective(
                id="rr_clear_path",
                title="Clear the boulder to Milk Road with a Powder Keg",
                description=(
                    "After obtaining a Powder Keg (and certification if needed), use it to "
                    "blast the boulder blocking the entrance to Romani Ranch."
                ),
                location="Milk Road",
                window=_tw(1, (6, 0), (23, 59)),
                provides_items=["Powder Keg"],
                keywords=[
                    "powder",
                    "keg",
                    "boulder",
                    "milk",
                    "road",
                    "romani",
                    "ranch",
                ],
            ),
            Objective(
                id="rr_learn_epona",
                title="Help Romani practice and learn Epona's Song",
                description=(
                    "Talk to Romani at Romani Ranch. She asks for help defending the ranch "
                    "from 'them' and teaches Link Epona's Song after a practice round."
                ),
                location="Romani Ranch",
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["rr_clear_path"],
                npc_id="romani",
                event_ref="romani_practice",
                keywords=[
                    "romani",
                    "epona",
                    "song",
                    "practice",
                    "aliens",
                    "ranch",
                ],
            ),
            Objective(
                id="rr_defend_ranch",
                title="Defend Romani Ranch from the alien invasion",
                description=(
                    "Return to Romani Ranch before 2:30 AM on the night of the First Day. "
                    "Use your bow to stop the aliens from reaching the barn until dawn."
                ),
                location="Romani Ranch",
                window=_tw(1, (26, 0), (29, 0)),
                prerequisites=["rr_learn_epona"],
                requires_items=["Bow"],
                npc_id="romani",
                event_ref="ranch_aliens",
                keywords=[
                    "aliens",
                    "them",
                    "barn",
                    "bow",
                    "defend",
                    "ranch",
                    "notte",
                ],
            ),
            Objective(
                id="rr_milk_delivery",
                title="Escort Cremia on the milk delivery to Clock Town",
                description=(
                    "On the Second Day at 6:00 PM, ride with Cremia in her wagon to deliver "
                    "milk to Clock Town. Defend the wagon from the Gorman Brothers with your bow."
                ),
                location="Milk Road",
                window=_tw(2, (18, 0), (23, 59)),
                prerequisites=["rr_defend_ranch"],
                npc_id="cremia",
                event_ref="ranch_milk_delivery",
                provides_masks=["Romani's Mask"],
                keywords=[
                    "cremia",
                    "milk",
                    "delivery",
                    "wagon",
                    "gorman",
                    "romani",
                    "mask",
                    "consegna",
                ],
            ),
        ],
    )

    deed_chain = Quest(
        id="deed_chain",
        name="Land Title Deed Chain",
        objectives=[
            Objective(
                id="dc_get_moon_tear",
                title="Obtain the Moon's Tear from the Astral Observatory",
                description=(
                    "Look through the telescope in the Astral Observatory and zoom in on the "
                    "top of the Clock Tower to make the moon drop a Moon's Tear."
                ),
                location="Astral Observatory",
                window=_tw(1, (6, 0), (23, 59)),
                provides_items=["Moon's Tear"],
                keywords=[
                    "moon",
                    "tear",
                    "observatory",
                    "clock",
                    "tower",
                    "lacrima",
                    "luna",
                ],
            ),
            Objective(
                id="dc_get_land_deed",
                title="Trade the Moon's Tear for the Land Title Deed",
                description=(
                    "Trade the Moon's Tear to the Business Scrub in South Clock Town to "
                    "obtain the Land Title Deed. Use his Deku Flower to reach the platform above."
                ),
                location="South Clock Town",
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dc_get_moon_tear"],
                requires_items=["Moon's Tear"],
                provides_items=["Land Title Deed"],
                keywords=[
                    "land",
                    "deed",
                    "title",
                    "moon",
                    "tear",
                    "business",
                    "scrub",
                    "titolo",
                    "terra",
                ],
            ),
            Objective(
                id="dc_land_to_swamp",
                title="Trade the Land Title Deed for the Swamp Title Deed",
                description=(
                    "Trade the Land Title Deed to the Business Scrub in Southern Swamp near the "
                    "Swamp Tourist Center to obtain the Swamp Title Deed."
                ),
                location="Southern Swamp",
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dc_get_land_deed"],
                requires_items=["Land Title Deed"],
                provides_items=["Swamp Title Deed"],
                keywords=[
                    "swamp",
                    "deed",
                    "title",
                    "land",
                    "palude",
                    "titolo",
                ],
            ),
            Objective(
                id="dc_swamp_to_mountain",
                title="Trade the Swamp Title Deed for the Mountain Title Deed",
                description=(
                    "Trade the Swamp Title Deed to the Business Scrub in Goron Village to obtain "
                    "the Mountain Title Deed."
                ),
                location="Goron Village",
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dc_land_to_swamp"],
                requires_items=["Swamp Title Deed"],
                provides_items=["Mountain Title Deed"],
                keywords=[
                    "mountain",
                    "deed",
                    "title",
                    "swamp",
                    "montagna",
                    "titolo",
                ],
            ),
            Objective(
                id="dc_mountain_to_bay",
                title="Trade the Mountain Title Deed for the Ocean Title Deed",
                description=(
                    "Trade the Mountain Title Deed to the Business Scrub in Lulu's room at "
                    "Zora Hall to obtain the Ocean Title Deed."
                ),
                location="Zora Hall",
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dc_swamp_to_mountain"],
                requires_items=["Mountain Title Deed"],
                provides_items=["Ocean Title Deed"],
                keywords=[
                    "ocean",
                    "deed",
                    "title",
                    "mountain",
                    "zora",
                    "oceano",
                    "titolo",
                ],
            ),
            Objective(
                id="dc_ocean_to_rupee",
                title="Trade the Ocean Title Deed for a Golden Rupee",
                description=(
                    "Trade the Ocean Title Deed to the Business Scrub in Ikana Canyon to "
                    "obtain a Golden Rupee."
                ),
                location="Ikana Canyon",
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dc_mountain_to_bay"],
                requires_items=["Ocean Title Deed"],
                provides_items=["Golden Rupee"],
                keywords=[
                    "ocean",
                    "deed",
                    "title",
                    "rupee",
                    "ikana",
                    "oro",
                    "rupia",
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
