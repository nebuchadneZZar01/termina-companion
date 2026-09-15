"""Mock/demo game knowledge.

The vertical slice models a few generic quests (Anju & Kafei as the main
example). Data is deliberately small and NOT lore-complete: it exists to
validate the architecture, not the game.

``KnowledgeBase.retrieve`` is the seam where RAG (vector retrieval over a real
wiki dump) will plug in later.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.domain import ClockTime, GameState, Goal, TimeWindow


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


class Quest(BaseModel):
    """A quest is just a named collection of objectives."""

    id: str
    name: str
    objectives: list[Objective]


class KnowledgeBase(BaseModel):
    """Holds all quest data and answers retrieval queries."""

    quests: list[Quest] = Field(default_factory=list)

    @property
    def all_objectives(self) -> list[Objective]:
        return [o for quest in self.quests for o in quest.objectives]

    def retrieve(self, game_state: GameState, goal: Goal) -> list[Objective]:
        """Return unfinished objectives, best keyword matches first."""
        done_quests = {qid for qid, status in game_state.quest_progress.items() if status == "done"}
        words = set(re.findall(r"[a-z']+", goal.description.lower()))
        scored: list[tuple[int, Objective]] = []
        for obj in self.all_objectives:
            if any(o in done_quests for o in _containing_quests(self.quests, obj.id)):
                continue
            score = len(words & set(obj.keywords))
            scored.append((score, obj))
        if scored and any(s > 0 for s, _ in scored):
            scored = [(s, o) for s, o in scored if s > 0]
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
    """Small vertical slice: Anju & Kafei (demo) plus a second generic quest."""
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
                keywords=["anju", "kafei", "letter", "reunite", "start"],
            ),
            Objective(
                id="ak_get_letter",
                title="Retrieve Kafei's letter from the mailbox",
                description="Kafei left a letter for you behind the Post Office.",
                location="Market District",
                window=_tw(2, (9, 0), (17, 0)),
                prerequisites=["ak_talk_to_anju"],
                keywords=["kafei", "letter", "mailbox", "post"],
            ),
            Objective(
                id="ak_deliver_letter",
                title="Give the letter to Kafei at the Curiosity Shop",
                description="Kafei is hiding out in the Curiosity Shop basement.",
                location="Curiosity Shop",
                window=_tw(3, (6, 0), (12, 0)),
                prerequisites=["ak_get_letter"],
                requires_items=["Kafei's Letter"],
                keywords=["kafei", "letter", "shop", "hideout"],
            ),
            Objective(
                id="ak_reunite",
                title="Reunite Anju and Kafei at the Stockpot Inn",
                description="Bring everyone together before the dawn of the Third Day.",
                location="Stockpot Inn",
                window=_tw(3, (22, 0), (23, 59)),
                prerequisites=["ak_deliver_letter"],
                keywords=["anju", "kafei", "reunite", "inn"],
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
                keywords=["bombers", "society", "hideout", "plan"],
            ),
            Objective(
                id="bm_find_hideout",
                title="Locate the hidden hideout behind the clock tower",
                description="The hideout entrance is marked by a odd drawing.",
                location="South Clock Town",
                window=_tw(1, (8, 0), (22, 0)),
                prerequisites=["bm_talk_leader"],
                requires_items=["Bomber's Notebook"],
                keywords=["hideout", "clock", "tower", "bombers"],
            ),
        ],
    )
    return KnowledgeBase(quests=[anju_kafei, bombers])
