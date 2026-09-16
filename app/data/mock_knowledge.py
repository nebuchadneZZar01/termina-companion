"""Mock/demo game knowledge.

The vertical slice models a few generic quests (Anju & Kafei as the main
example), set in Clock Town with a handful of NPCs, schedules and timed
events. Data is deliberately small and NOT lore-complete: it exists to
validate the architecture, not the game.

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
    keywords: list[str] = Field(default_factory=list)
    npc_id: str = ""  # id of the NPC the player must interact with, if any
    event_ref: str = ""  # id of the ScheduledEvent this objective tracks, if any


class Quest(BaseModel):
    """A quest is just a named collection of objectives."""

    id: str
    name: str
    objectives: list[Objective]


class KnowledgeBase(BaseModel):
    """Holds all quest data and answers retrieval queries."""

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
    return [q.id for q in quests if any(o.id == objective_id for o in q.objectives)]


def _tw(day: int, start: tuple[int, int], end: tuple[int, int]) -> TimeWindow:
    """Helper to build a TimeWindow from (hour, minute) pairs."""
    sh, sm = start
    eh, em = end
    return TimeWindow(
        start=ClockTime(day=day, hour=sh, minute=sm), end=ClockTime(day=day, hour=eh, minute=em)
    )


def build_default_knowledge() -> KnowledgeBase:
    """Small vertical slice: Clock Town, a few NPCs and timed events."""
    locations = [
        Location(id="stockpot_inn", name="Stockpot Inn", area="West Clock Town"),
        Location(id="curiosity_shop", name="Curiosity Shop", area="South Clock Town"),
        Location(id="market_district", name="Market District", area="East Clock Town"),
        Location(id="post_office", name="Post Office", area="West Clock Town"),
        Location(id="south_clock_town", name="South Clock Town", area="Clock Town"),
        Location(id="north_clock_town", name="North Clock Town", area="Clock Town"),
    ]
    npcs = [
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
    ]
    events = [
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
        ScheduledEvent(
            id="bm_hideout_gathering",
            name="Bombers gather at the hideout",
            location="South Clock Town",
            window=_tw(1, (8, 0), (22, 0)),
        ),
    ]
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
    return KnowledgeBase(
        quests=[anju_kafei, bombers],
        locations=locations,
        npcs=npcs,
        events=events,
    )
