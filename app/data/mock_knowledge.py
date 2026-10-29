"""Mock/demo game knowledge.

The vertical slice models several quests across Majora's Mask areas, with
NPCs, schedules, timed events, mask and item requirements. Data is
deliberately NOT lore-complete: it exists to validate the architecture,
not the game.

Agents read this data through the MCP tools in ``app.mcp.tools``, never
directly.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

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
    id: str
    name: str
    area: str


class NPC(BaseModel):
    id: str
    name: str
    location: str
    schedule: list[TimeWindow] = Field(default_factory=list)

    def available_at(self, t: ClockTime) -> bool:
        return any(w.contains(t) for w in self.schedule)


class ScheduledEvent(BaseModel):
    id: str
    name: str
    location: str
    window: TimeWindow
    description: str = ""


class Objective(BaseModel):
    id: str
    title: str
    description: str = ""
    location: str
    window: TimeWindow
    # A recurring objective is available again on every game day, with the same
    # time of day, for as long as the cycle lasts. It models a place or an NPC
    # you can visit, not a scene that happens once, so it can never fall into
    # the past. A one-off objective happens once per cycle: once its window
    # closes it is gone until the Song of Time rewinds the three days.
    recurring: bool = False
    prerequisites: list[str] = Field(default_factory=list)
    requires_items: list[str] = Field(default_factory=list)
    requires_masks: list[str] = Field(default_factory=list)
    requires_quests: list[str] = Field(default_factory=list)
    provides_items: list[str] = Field(default_factory=list)
    provides_masks: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    npc_id: str = ""
    event_ref: str = ""

    @model_validator(mode="after")
    def _recurring_is_not_a_dated_event(self) -> "Objective":
        """Reject an objective that claims to both repeat and happen once.

        A scheduled event is a single dated beat (a delivery, a night watch), so
        its availability cannot recur every day. Catching the contradiction when
        the knowledge base loads keeps a mistyped flag from silently turning a
        one-off scene into a daily one.

        returns:
            Objective: the validated objective.

        raises:
            ValueError: when a recurring objective is bound to an event.
        """
        if self.recurring and self.event_ref:
            raise ValueError(
                f"objective {self.id!r} is recurring and bound to event {self.event_ref!r}"
            )
        return self


class Quest(BaseModel):
    id: str
    name: str
    objectives: list[Objective]


class KnowledgeBase(BaseModel):
    quests: list[Quest] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    npcs: list[NPC] = Field(default_factory=list)
    events: list[ScheduledEvent] = Field(default_factory=list)

    @property
    def all_objectives(self) -> list[Objective]:
        return [o for quest in self.quests for o in quest.objectives]

    def npc(self, npc_id: str) -> NPC | None:
        return next((n for n in self.npcs if n.id == npc_id), None)

    def event(self, event_id: str) -> ScheduledEvent | None:
        return next((e for e in self.events if e.id == event_id), None)


def _tw(day: int, start: tuple[int, int], end: tuple[int, int]) -> TimeWindow:
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
    sh, sm = start
    eh, em = end
    return TimeWindow(
        start=ClockTime(day=start_day, hour=sh, minute=sm),
        end=ClockTime(day=end_day, hour=eh, minute=em),
    )


def build_default_knowledge() -> KnowledgeBase:
    locations = [
        Location(id="clock_tower", name="Clock Tower", area="Clock Town"),
        Location(id="stockpot_inn", name="Stockpot Inn", area="West Clock Town"),
        Location(id="curiosity_shop", name="Curiosity Shop", area="South Clock Town"),
        Location(id="market_district", name="Market District", area="East Clock Town"),
        Location(id="mayor_residence", name="Mayor's Residence", area="East Clock Town"),
        Location(id="post_office", name="Post Office", area="West Clock Town"),
        Location(id="laundry_pool", name="Laundry Pool", area="South Clock Town"),
        Location(id="south_clock_town", name="South Clock Town", area="Clock Town"),
        Location(id="north_clock_town", name="North Clock Town", area="Clock Town"),
        Location(id="east_clock_town", name="East Clock Town", area="Clock Town"),
        Location(id="west_clock_town", name="West Clock Town", area="Clock Town"),
        Location(id="swamp_spider_house", name="Swamp Spider House", area="Southern Swamp"),
        Location(id="dekupalace", name="Deku Palace", area="Southern Swamp"),
        Location(id="woodfall", name="Woodfall", area="Southern Swamp"),
        Location(id="woodfall_temple", name="Woodfall Temple", area="Southern Swamp"),
        Location(id="deku_shrine", name="Deku Shrine", area="Southern Swamp"),
        Location(id="goron_shrine", name="Goron Shrine", area="Mountain Village"),
        Location(id="snowhead", name="Snowhead", area="Mountain Village"),
        Location(id="goron_village", name="Goron Village", area="Mountain Village"),
        Location(id="goron_graveyard", name="Goron Graveyard", area="Mountain Village"),
        Location(id="lone_peak_shrine", name="Lone Peak Shrine", area="Mountain Village"),
        Location(id="path_to_snowhead", name="Path to Snowhead", area="Mountain Village"),
        Location(id="zora_hall", name="Zora Hall", area="Great Bay"),
        Location(id="zora_cape", name="Zora Cape", area="Great Bay"),
        Location(id="pinnacle_rock", name="Pinnacle Rock", area="Great Bay"),
        Location(id="great_bay_coast", name="Great Bay Coast", area="Great Bay"),
        Location(id="pirates_fortress", name="Pirates' Fortress", area="Great Bay"),
        Location(id="marine_research_lab", name="Marine Research Lab", area="Great Bay"),
        Location(id="canyon_shrine", name="Canyon Shrine", area="Ikana Canyon"),
        Location(id="ancient_castle_ikana", name="Ancient Castle of Ikana", area="Ikana Canyon"),
        Location(id="sakons_hideout", name="Sakon's Hideout", area="Ikana Canyon"),
        Location(id="ikana_graveyard", name="Ikana Graveyard", area="Ikana Canyon"),
        Location(id="music_box_house", name="Music Box House", area="Ikana Canyon"),
        Location(id="romani_ranch", name="Romani Ranch", area="Romani Ranch"),
        Location(id="milk_road", name="Milk Road", area="Termina"),
        Location(id="southern_swamp", name="Southern Swamp", area="Southern Swamp"),
        Location(id="termina_field", name="Termina Field", area="Termina"),
        Location(id="astral_observatory", name="Astral Observatory", area="Termina"),
    ]

    npcs = [
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
            schedule=[_tw_span(2, (15, 0), 3, (13, 0)), _tw(3, (18, 0), (27, 0))],
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
            id="jim",
            name="Jim",
            location="North Clock Town",
            schedule=[_tw(1, (6, 0), (20, 0)), _tw(2, (6, 0), (20, 0)), _tw(3, (6, 0), (20, 0))],
        ),
        NPC(
            id="goron_elder",
            name="Goron Elder",
            location="Goron Shrine",
            schedule=[_tw_span(1, (6, 0), 3, (22, 0))],
        ),
        NPC(
            id="darmani",
            name="Darmani",
            location="Goron Graveyard",
            schedule=[_tw_span(1, (6, 0), 3, (29, 0))],
        ),
        NPC(
            id="baby_goron",
            name="Baby Goron",
            location="Goron Shrine",
            schedule=[_tw_span(1, (6, 0), 3, (23, 59))],
        ),
        NPC(
            id="mikau",
            name="Mikau",
            location="Great Bay Coast",
            schedule=[_tw_span(1, (6, 0), 3, (23, 59))],
        ),
        NPC(
            id="indigo_gos",
            name="Indigo-Go's",
            location="Zora Hall",
            schedule=[_tw_span(1, (6, 0), 3, (23, 59))],
        ),
        NPC(
            id="lulu",
            name="Lulu",
            location="Zora Hall",
            schedule=[_tw_span(1, (6, 0), 3, (23, 59))],
        ),
        NPC(
            id="dekuboss",
            name="Deku King",
            location="Deku Palace",
            schedule=[_tw_span(1, (6, 0), 3, (23, 59))],
        ),
        NPC(
            id="deku_butler",
            name="Deku Butler",
            location="Deku Shrine",
            schedule=[_tw_span(1, (6, 0), 3, (23, 59))],
        ),
        NPC(
            id="monkey",
            name="Monkey",
            location="Deku Palace",
            schedule=[_tw_span(1, (6, 0), 3, (23, 59))],
        ),
        NPC(
            id="koume",
            name="Koume",
            location="Southern Swamp",
            schedule=[_tw_span(1, (6, 0), 3, (23, 59))],
        ),
        NPC(
            id="romani",
            name="Romani",
            location="Romani Ranch",
            schedule=[_tw(1, (6, 0), (18, 0)), _tw(2, (6, 0), (18, 0))],
        ),
        NPC(
            id="cremia",
            name="Cremia",
            location="Romani Ranch",
            schedule=[_tw(2, (18, 0), (19, 45))],
        ),
        NPC(
            id="pamela",
            name="Pamela",
            location="Music Box House",
            schedule=[_tw_span(1, (6, 0), 3, (29, 0))],
        ),
        NPC(
            id="shiro",
            name="Shiro",
            location="Canyon Shrine",
            schedule=[_tw(2, (22, 0), (23, 59)), _tw(3, (22, 0), (23, 59))],
        ),
        NPC(
            id="mask_salesman",
            name="Happy Mask Salesman",
            location="Clock Tower",
            schedule=[_tw_span(1, (6, 0), 3, (23, 59))],
        ),
        NPC(
            id="captain_keeta",
            name="Captain Keeta",
            location="Ikana Graveyard",
            schedule=[_tw_span(1, (6, 0), 3, (23, 59))],
        ),
        NPC(
            id="flat",
            name="Flat",
            location="Ikana Graveyard",
            schedule=[_tw_span(1, (6, 0), 3, (23, 59))],
        ),
    ]

    events = [
        ScheduledEvent(
            id="ak_letter_delivery",
            name="Kafei's letter is delivered",
            location="Stockpot Inn",
            window=_tw(1, (14, 0), (14, 20)),
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
        ScheduledEvent(
            id="ranch_aliens",
            name="Romani defends the ranch from aliens",
            location="Romani Ranch",
            window=_tw(1, (26, 30), (29, 15)),
            description="Aliens attack the ranch.",
        ),
        ScheduledEvent(
            id="ranch_milk_delivery",
            name="Cremia delivers milk to Clock Town",
            location="Milk Road",
            window=_tw(2, (18, 0), (19, 45)),
            description="Cremia's wagon ride.",
        ),
        ScheduledEvent(
            id="ikana_piano",
            name="Ghost plays the piano in Ikana Castle",
            location="Ancient Castle of Ikana",
            window=_tw(2, (24, 0), (28, 0)),
        ),
        ScheduledEvent(
            id="snowhead_blizzard",
            name="Blizzard rages near Snowhead",
            location="Snowhead",
            window=_tw_span(1, (6, 0), 3, (23, 59)),
        ),
    ]

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
                    "residenza",
                    "sindaco",
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
                    "lettera",
                    "locanda",
                    "parla",
                ],
            ),
            Objective(
                id="ak_meet_in_kitchen",
                title="Meet Anju in the Stockpot Inn kitchen",
                description="Anju gives you a letter for Kafei during the night.",
                location="Stockpot Inn",
                window=_tw(1, (23, 30), (29, 0)),
                prerequisites=["ak_talk_to_anju"],
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
                    "buca",
                    "lavatoio",
                    "lettera",
                    "posta",
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
                    "ciondolo",
                    "nascondiglio",
                    "negozio",
                ],
            ),
            Objective(
                id="ak_deliver_pendant",
                title="Deliver the Pendant of Memories to Anju",
                description="Bring Kafei's pendant back to Anju at the Stockpot Inn.",
                location="Stockpot Inn",
                window=_tw(3, (8, 0), (18, 0)),
                prerequisites=["ak_meet_kafei"],
                requires_items=["Pendant of Memories"],
                npc_id="anju",
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
                    "maschera",
                    "nascondiglio",
                    "sole",
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
                    "couple",
                    "mask",
                    "inn",
                    "stockpot",
                    "coppia",
                    "innamorati",
                    "locanda",
                    "mattina",
                    "riunione",
                    "riunire",
                    "riunisci",
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
                    "Use a Deku Bubble to pop the balloon Jim is shooting at and challenge him to "
                    "hide-and-seek."
                ),
                location="North Clock Town",
                window=_tw(1, (6, 0), (20, 0)),
                npc_id="jim",
                keywords=[
                    "bombers",
                    "balloon",
                    "majora",
                    "jim",
                    "hide",
                    "seek",
                    "society",
                    "palloncino",
                ],
            ),
            Objective(
                id="bm_hide_and_seek",
                title="Find all five Bombers in hide-and-seek",
                description=(
                    "Locate all five Bombers scattered around Clock Town within the time limit."
                ),
                location="North Clock Town",
                window=_tw(1, (6, 0), (21, 0)),
                prerequisites=["bm_pop_balloon"],
                npc_id="jim",
                keywords=["bombers", "hide", "seek", "gang", "code", "nascondino"],
            ),
            Objective(
                id="bm_get_notebook",
                title="Obtain the Bombers' Notebook",
                description=(
                    "After completing hide-and-seek, receive the Bombers' Notebook from Jim. The "
                    "notebook tracks side quests throughout Termina."
                ),
                location="North Clock Town",
                window=_tw(1, (6, 0), (22, 0)),
                prerequisites=["bm_hide_and_seek"],
                provides_items=["Bombers' Notebook"],
                npc_id="jim",
                keywords=["bombers", "notebook", "taccuino", "jim", "member", "code"],
            ),
            Objective(
                id="bm_enter_hideout",
                title="Enter the Bombers' Hideout using the secret code",
                description=(
                    "Use the Bombers' secret code at the "
                    "hideout entrance in East Clock Town to gain "
                    "access."
                ),
                location="East Clock Town",
                window=_tw(1, (6, 0), (23, 0)),
                prerequisites=["bm_get_notebook"],
                requires_items=["Bombers' Notebook"],
                keywords=[
                    "hideout",
                    "code",
                    "password",
                    "sewer",
                    "east",
                    "astral",
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
                id="dg_get_lens",
                title="Obtain the Lens of Truth from the Lone Peak Shrine",
                description=(
                    "Obtain the Lens of Truth to see things that are invisible to the naked eye."
                ),
                location="Lone Peak Shrine",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                provides_items=["Lens of Truth"],
                keywords=[
                    "lens",
                    "truth",
                    "lone",
                    "peak",
                    "shrine",
                    "lente",
                    "verita",
                    "curiosità",
                    "negozio",
                    "verità",
                ],
            ),
            Objective(
                id="dg_see_darmani",
                title="See Darmani's spirit at the Goron Graveyard with the Lens of Truth",
                description="Use the Lens of Truth to see Darmani's spirit at the Goron Graveyard.",
                location="Goron Graveyard",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dg_get_lens"],
                requires_items=["Lens of Truth"],
                npc_id="darmani",
                keywords=[
                    "darmani",
                    "ghost",
                    "spirit",
                    "lens",
                    "graveyard",
                    "fantasma",
                    "nanna",
                    "ninna",
                    "santuario",
                    "spirito",
                ],
            ),
            Objective(
                id="dg_heal_darmani",
                title="Heal Darmani's spirit with the Song of Healing",
                description=(
                    "Play the Song of Healing for Darmani's spirit to soothe him. In return, he "
                    "grants you the Goron Mask."
                ),
                location="Goron Graveyard",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dg_see_darmani"],
                provides_masks=["Goron Mask"],
                npc_id="darmani",
                keywords=[
                    "darmani",
                    "healing",
                    "song",
                    "goron",
                    "mask",
                    "canzone",
                    "guarigione",
                    "maschera",
                ],
            ),
        ],
    )

    goron_lullaby = Quest(
        id="goron_lullaby",
        name="Goron Lullaby",
        objectives=[
            Objective(
                id="dg_get_hot_spring",
                title="Get hot spring water from Darmani's grave",
                description=(
                    "Obtain hot spring water from Darmani's grave to thaw the frozen Goron Elder."
                ),
                location="Goron Graveyard",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                requires_quests=["darmani_spirit"],
                provides_items=["Hot Spring Water"],
                keywords=["hot", "spring", "water", "darmani", "grave"],
            ),
            Objective(
                id="dg_thaw_elder",
                title="Thaw the frozen Goron Elder on the path to Snowhead",
                description=(
                    "Use hot spring water to thaw the frozen "
                    "Goron Elder and learn the Lullaby Intro."
                ),
                location="Path to Snowhead",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dg_get_hot_spring"],
                requires_items=["Hot Spring Water"],
                npc_id="goron_elder",
                keywords=["elder", "thaw", "lullaby", "intro", "snowhead"],
            ),
            Objective(
                id="dg_learn_lullaby",
                title="Learn the full Goron Lullaby from the Baby Goron in Goron Shrine",
                description="Learn the full Goron Lullaby from the Baby Goron in Goron Shrine.",
                location="Goron Shrine",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dg_thaw_elder"],
                npc_id="baby_goron",
                keywords=["baby", "goron", "lullaby", "full", "shrine"],
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
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                npc_id="mikau",
                provides_masks=["Zora Mask"],
                requires_quests=["romani_ranch"],
                keywords=[
                    "zora",
                    "mask",
                    "mikau",
                    "healing",
                    "song",
                    "coast",
                    "guarigione",
                    "maschera",
                    "spiaggia",
                ],
            ),
            Objective(
                id="mm_talk_band",
                title="Talk to the Indigo-Go's about Lulu's stolen eggs",
                description=(
                    "In Zora form, speak to the members of "
                    "the Indigo-Go's at Zora Hall. They reveal "
                    "that Lulu's eggs were stolen by Gerudo "
                    "Pirates and hidden at Pirates' Fortress "
                    "and Pinnacle Rock."
                ),
                location="Zora Hall",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["mm_heal_mikau"],
                npc_id="indigo_gos",
                keywords=["indigo", "zora", "hall", "eggs", "lulu", "pirates", "uova"],
            ),
            Objective(
                id="mm_get_fortress_eggs",
                title="Retrieve four Zora Eggs from the Pirates' Fortress",
                description=(
                    "Swim through the Pirates' Fortress in Zora form and recover four of Lulu's "
                    "stolen eggs."
                ),
                location="Pirates' Fortress",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["mm_talk_band"],
                keywords=["eggs", "pirates", "fortress", "uova"],
            ),
            Objective(
                id="mm_get_pinnacle_eggs",
                title="Retrieve three Zora Eggs from Pinnacle Rock",
                description="Recover the remaining three Zora Eggs from Pinnacle Rock.",
                location="Pinnacle Rock",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["mm_get_fortress_eggs"],
                keywords=["eggs", "pinnacle", "rock"],
            ),
            Objective(
                id="mm_deliver_eggs",
                title="Deliver Lulu's eggs to the Marine Research Lab",
                description="Deliver all seven Zora Eggs to the Marine Research Lab.",
                location="Marine Research Lab",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["mm_get_pinnacle_eggs"],
                keywords=["eggs", "lab", "deliver"],
            ),
            Objective(
                id="mm_learn_bossa_nova",
                title="Learn the New Wave Bossa Nova from the baby Zoras",
                description="The baby Zoras teach Link the New Wave Bossa Nova at Zora Hall.",
                location="Zora Hall",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["mm_deliver_eggs"],
                npc_id="indigo_gos",
                keywords=["bossa", "nova", "song", "mikau", "eggs", "canzone", "lulu"],
            ),
            Objective(
                id="mm_play_for_lulu",
                title="Play the New Wave Bossa Nova for Lulu at Zora Cape",
                description=(
                    "Play the New Wave Bossa Nova for Lulu at Zora Cape to help her recover."
                ),
                location="Zora Cape",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["mm_learn_bossa_nova"],
                npc_id="lulu",
                keywords=["lulu", "cape", "song", "bossa", "nova"],
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
                description="Travel to Ikana Canyon and visit the Music Box House.",
                location="Music Box House",
                recurring=True,
                window=_tw(1, (6, 0), (29, 0)),
                npc_id="pamela",
                keywords=[
                    "pamela",
                    "father",
                    "gibdo",
                    "music",
                    "box",
                    "house",
                    "curse",
                    "cursed",
                    "ikana",
                ],
            ),
            Objective(
                id="pf_restore_river",
                title="Restore the river with the Song of Storms",
                description=(
                    "Use the Song of Storms to restore the dried riverbed so that Pamela's father "
                    "can be reached."
                ),
                location="Ikana Canyon",
                recurring=True,
                window=_tw(1, (6, 0), (29, 0)),
                prerequisites=["pf_find_pamela"],
                requires_quests=["song_of_storms"],
                keywords=["pamela", "father", "river", "storm", "song", "music", "box", "house"],
            ),
            Objective(
                id="pf_enter_house",
                title="Enter the Music Box House to reach the basement",
                description=(
                    "Sneak into the Music Box House to reach the basement where Pamela's father "
                    "rests."
                ),
                location="Music Box House",
                recurring=True,
                window=_tw(1, (6, 0), (29, 0)),
                prerequisites=["pf_restore_river"],
                npc_id="pamela",
                keywords=[
                    "pamela",
                    "father",
                    "enter",
                    "house",
                    "basement",
                    "sneak",
                    "music",
                    "box",
                ],
            ),
            Objective(
                id="pf_free_father",
                title="Free Pamela's father with the Song of Healing",
                description=(
                    "Play the Song of Healing for Pamela's "
                    "father to break the curse. In return, he "
                    "grants you the Gibdo Mask."
                ),
                location="Music Box House",
                recurring=True,
                window=_tw(1, (6, 0), (29, 0)),
                prerequisites=["pf_enter_house"],
                provides_masks=["Gibdo Mask"],
                npc_id="pamela",
                keywords=[
                    "pamela",
                    "father",
                    "free",
                    "break",
                    "curse",
                    "healing",
                    "song",
                    "gibdo",
                    "mask",
                    "music",
                    "box",
                    "house",
                    "guarigione",
                    "liberare",
                ],
            ),
            Objective(
                id="pf_reunite_pamela",
                title="Reunite Pamela with her father",
                description=(
                    "Pamela is overjoyed to be reunited with her father after breaking his curse."
                ),
                location="Music Box House",
                recurring=True,
                window=_tw(1, (6, 0), (29, 0)),
                prerequisites=["pf_free_father"],
                npc_id="pamela",
                keywords=["pamela", "father", "music", "box", "house", "ikana", "riunione"],
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
                    "After retrieving the Ocarina of Time and turning back time with the Song of "
                    "Time, learn the Song of Healing from the Happy Mask Salesman to receive the "
                    "Deku Mask."
                ),
                location="Clock Tower",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                provides_masks=["Deku Mask"],
                npc_id="mask_salesman",
                keywords=["deku", "mask", "salesman", "healing", "song", "maschera", "venditore"],
            ),
            Objective(
                id="dp_talk_king",
                title="Speak to the Deku King at Deku Palace",
                description=(
                    "Enter Deku Palace in Deku form and speak to the Deku King. He blames you for "
                    "the disappearance of the Deku Princess."
                ),
                location="Deku Palace",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dp_get_deku_mask"],
                requires_masks=["Deku Mask"],
                npc_id="dekuboss",
                keywords=["deku", "princess", "king", "palace", "palazzo", "principessa", "re"],
            ),
            Objective(
                id="dp_learn_sonata",
                title="Learn the Sonata of Awakening from the Monkey",
                description=(
                    "Talk to the Monkey in the Deku Palace "
                    "dungeon to learn the Sonata of Awakening."
                ),
                location="Deku Palace",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dp_talk_king"],
                npc_id="monkey",
                keywords=["monkey", "sonata", "awakening", "song"],
            ),
            Objective(
                id="dp_save_koume",
                title="Save Koume in Southern Swamp to obtain the boat cruise",
                description=(
                    "Rescue Koume in Southern Swamp to obtain the boat cruise to Woodfall Temple."
                ),
                location="Southern Swamp",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dp_learn_sonata"],
                npc_id="koume",
                keywords=["koume", "swamp", "boat", "cruise"],
            ),
            Objective(
                id="dp_enter_woodfall",
                title="Enter Woodfall Temple through Southern Swamp",
                description=(
                    "Use the boat cruise and Sonata of Awakening to reach Woodfall Temple to find "
                    "the source of the poison."
                ),
                location="Woodfall Temple",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dp_save_koume"],
                keywords=["woodfall", "swamp", "temple", "sonata", "palude"],
            ),
            Objective(
                id="dp_rescue_princess",
                title="Defeat Odolwa and rescue the Deku Princess",
                description=(
                    "Clear Woodfall Temple and defeat Odolwa. "
                    "Rescue the Deku Princess, capture her "
                    "in an Empty Bottle."
                ),
                location="Woodfall Temple",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dp_enter_woodfall"],
                requires_items=["Empty Bottle"],
                keywords=["odolwa", "princess", "bottle", "temple", "rescue"],
            ),
            Objective(
                id="dp_return_princess",
                title="Return the Deku Princess to the Deku King",
                description=(
                    "Return the Deku Princess to the Deku King in Deku Palace to lift the blame."
                ),
                location="Deku Palace",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dp_rescue_princess"],
                keywords=["princess", "return", "king", "palace"],
            ),
            Objective(
                id="dp_butler_race",
                title="Race the Deku Butler for the Mask of Scents",
                description=(
                    "Race the Deku Butler through the Deku Shrine to earn the Mask of Scents."
                ),
                location="Deku Shrine",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dp_return_princess"],
                provides_masks=["Mask of Scents"],
                npc_id="deku_butler",
                keywords=["butler", "race", "mask", "scents", "shrine", "gara", "maschera"],
            ),
        ],
    )

    romani_ranch = Quest(
        id="romani_ranch",
        name="Romani Ranch",
        objectives=[
            Objective(
                id="rr_get_powder_keg",
                title="Get a Powder Keg from the Goron in Goron Village",
                description=(
                    "Obtain a Powder Keg (with certification as needed) to blast the boulder "
                    "blocking Milk Road."
                ),
                location="Goron Village",
                window=_tw(1, (6, 0), (23, 59)),
                requires_quests=["darmani_spirit"],
                provides_items=["Powder Keg"],
                keywords=["powder", "keg", "village", "romani"],
            ),
            Objective(
                id="rr_clear_path",
                title="Clear the boulder to Milk Road with a Powder Keg",
                description=(
                    "Use the Powder Keg to blast the boulder blocking the entrance to Romani Ranch."
                ),
                location="Milk Road",
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["rr_get_powder_keg"],
                requires_items=["Powder Keg"],
                keywords=["boulder", "milk", "road", "romani", "ranch"],
            ),
            Objective(
                id="rr_learn_epona",
                title="Help Romani practice and learn Epona's Song",
                description=(
                    "Talk to Romani at Romani Ranch. She asks for help defending the ranch from "
                    "'them' and teaches Link Epona's Song."
                ),
                location="Romani Ranch",
                window=_tw(1, (6, 0), (18, 0)),
                prerequisites=["rr_clear_path"],
                npc_id="romani",
                keywords=["romani", "epona", "song", "practice", "aliens", "ranch"],
            ),
            Objective(
                id="rr_defend_ranch",
                title="Defend Romani Ranch from the alien invasion",
                description=(
                    "Return to Romani Ranch before 2:30 AM on the night of the First Day. Use your "
                    "bow to stop the aliens from reaching the barn until dawn."
                ),
                location="Romani Ranch",
                window=_tw(1, (26, 30), (29, 15)),
                prerequisites=["rr_learn_epona"],
                requires_items=["Bow"],
                npc_id="romani",
                event_ref="ranch_aliens",
                keywords=["aliens", "them", "barn", "bow", "defend", "ranch", "notte"],
            ),
            Objective(
                id="rr_milk_delivery",
                title="Escort Cremia on the milk delivery to Clock Town",
                description=(
                    "On the Second Day at 6:00 PM, ride with "
                    "Cremia in her wagon to deliver milk to "
                    "Clock Town. Defend the wagon from the Gorman Brothers with your bow."
                ),
                location="Milk Road",
                window=_tw(2, (18, 0), (19, 45)),
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

    song_of_storms = Quest(
        id="song_of_storms",
        name="Song of Storms",
        objectives=[
            Objective(
                id="ss_wake_keeta",
                title="Wake Captain Keeta in Ikana Graveyard with the Sonata of Awakening",
                description=(
                    "Use the Sonata of Awakening to wake Captain Keeta in the Ikana Graveyard."
                ),
                location="Ikana Graveyard",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                requires_quests=["deku_princess"],
                npc_id="captain_keeta",
                keywords=["keeta", "graveyard", "sonata", "awakening"],
            ),
            Objective(
                id="ss_open_grave",
                title="Open the grave of the Composer Brother Flat",
                description="Open the grave of the Composer Brother Flat in the Ikana Graveyard.",
                location="Ikana Graveyard",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["ss_wake_keeta"],
                keywords=["grave", "flat", "composer", "ikana"],
            ),
            Objective(
                id="ss_learn_song_storms",
                title="Learn the Song of Storms from Flat",
                description=(
                    "Learn the Song of Storms from the ghost of Flat in the Ikana Graveyard."
                ),
                location="Ikana Graveyard",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["ss_open_grave"],
                npc_id="flat",
                keywords=["song", "storms", "flat", "graveyard"],
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
                    "Look through the telescope in the Astral "
                    "Observatory and zoom in on the top of "
                    "the Clock Tower to make the moon drop a Moon's Tear."
                ),
                location="Astral Observatory",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                provides_items=["Moon's Tear"],
                requires_quests=["deku_princess"],
                keywords=["moon", "tear", "observatory", "clock", "tower", "lacrima", "luna"],
            ),
            Objective(
                id="dc_get_land_deed",
                title="Trade the Moon's Tear for the Town Title Deed",
                description=(
                    "Trade the Moon's Tear to the Business Scrub in South Clock Town to obtain the "
                    "Town Title Deed."
                ),
                location="South Clock Town",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dc_get_moon_tear"],
                requires_items=["Moon's Tear"],
                provides_items=["Town Title Deed"],
                keywords=["town", "deed", "title", "moon", "tear", "scrub", "terra", "titolo"],
            ),
            Objective(
                id="dc_land_to_swamp",
                title="Trade the Town Title Deed for the Swamp Title Deed",
                description=(
                    "Trade the Town Title Deed to the Business "
                    "Scrub in Southern Swamp to obtain the "
                    "Swamp Title Deed."
                ),
                location="Southern Swamp",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dc_get_land_deed"],
                requires_items=["Town Title Deed"],
                provides_items=["Swamp Title Deed"],
                keywords=["swamp", "deed", "title", "town", "palude", "titolo"],
            ),
            Objective(
                id="dc_swamp_to_mountain",
                title="Trade the Swamp Title Deed for the Mountain Title Deed",
                description=(
                    "Trade the Swamp Title Deed to the Business "
                    "Scrub in Goron Village to obtain the "
                    "Mountain Title Deed."
                ),
                location="Goron Village",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dc_land_to_swamp"],
                requires_items=["Swamp Title Deed"],
                provides_items=["Mountain Title Deed"],
                keywords=["mountain", "deed", "title", "swamp", "montagna", "titolo"],
            ),
            Objective(
                id="dc_mountain_to_bay",
                title="Trade the Mountain Title Deed for the Ocean Title Deed",
                description=(
                    "Trade the Mountain Title Deed to the "
                    "Business Scrub in Lulu's room at Zora Hall "
                    "to obtain the Ocean Title Deed."
                ),
                location="Zora Hall",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dc_swamp_to_mountain"],
                requires_items=["Mountain Title Deed"],
                provides_items=["Ocean Title Deed"],
                requires_quests=["mikau_memory", "romani_ranch"],
                keywords=["ocean", "deed", "title", "mountain", "zora", "oceano", "titolo"],
            ),
            Objective(
                id="dc_ocean_to_rupee",
                title="Trade the Ocean Title Deed for a Huge Rupee",
                description=(
                    "Trade the Ocean Title Deed to the Business Scrub in Ikana Canyon to obtain a "
                    "Huge Rupee."
                ),
                location="Ikana Canyon",
                recurring=True,
                window=_tw(1, (6, 0), (23, 59)),
                prerequisites=["dc_mountain_to_bay"],
                requires_items=["Ocean Title Deed"],
                provides_items=["Huge Rupee"],
                keywords=["ocean", "deed", "title", "rupee", "ikana", "huge", "oro", "rupia"],
            ),
        ],
    )

    return KnowledgeBase(
        quests=[
            anju_kafei,
            bombers,
            darmani_spirit,
            goron_lullaby,
            mikau_memory,
            pamela_father,
            deku_princess,
            romani_ranch,
            song_of_storms,
            deed_chain,
        ],
        locations=locations,
        npcs=npcs,
        events=events,
    )
