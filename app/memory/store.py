"""In-memory implementation of the MemoryStore protocol."""

from __future__ import annotations

import re
import threading
import uuid
from datetime import datetime

from app.memory.models import Episode, PlayerPreferences

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


class MemoryStore:
    """Protocol for player memory: preferences plus past episodes.

    The in-memory class below is the only implementation for Phase 8.
    A future persistent store (JSON/SQLite) implements these same methods
    and is selected in :func:`get_memory_store`.
    """

    def get_preferences(self) -> PlayerPreferences: ...
    def save_preferences(self, prefs: PlayerPreferences) -> None: ...
    def save_episode(self, episode: Episode) -> None: ...

    def search_episodes(self, goal: str, location: str = "", limit: int = 3) -> list[Episode]:
        """Episodes whose goal shares a token with ``goal``; may be empty.

        ``location`` only breaks ties. No fallback to recent episodes: an
        unrelated past plan must never reach the planner.
        """
        ...

    def recent_episodes(self, limit: int = 5) -> list[Episode]: ...
    def clear(self) -> None: ...


class InMemoryMemoryStore(MemoryStore):
    """Thread-safe in-process store. No persistence across restarts."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._prefs = PlayerPreferences()
        self._episodes: list[Episode] = []

    def get_preferences(self) -> PlayerPreferences:
        with self._lock:
            return self._prefs.model_copy(deep=True)

    def save_preferences(self, prefs: PlayerPreferences) -> None:
        with self._lock:
            self._prefs = prefs.model_copy(deep=True)

    def save_episode(self, episode: Episode) -> None:
        with self._lock:
            if not episode.id:
                episode = episode.model_copy(update={"id": uuid.uuid4().hex})
            self._episodes.append(episode)

    # ponytail: keyword ranking only, matches with score 0 are dropped so an
    # unrelated past plan never pollutes the planner prompt. Ceiling: semantic
    # match; upgrade path: FastEmbed vectors already used by RAG.
    def search_episodes(self, goal: str, location: str = "", limit: int = 3) -> list[Episode]:
        with self._lock:
            episodes = list(self._episodes)
        if not episodes:
            return []
        goal_tokens = _tokens(goal)
        scored: list[tuple[int, datetime, Episode]] = []
        for ep in episodes:
            overlap = len(goal_tokens & _tokens(ep.goal))
            if overlap == 0:
                continue
            score = overlap
            if ep.location and location and ep.location.lower() == location.lower():
                score += 2
            scored.append((score, ep.created_at, ep))
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return [ep for _, _, ep in scored[:limit]]

    def recent_episodes(self, limit: int = 5) -> list[Episode]:
        with self._lock:
            episodes = list(self._episodes)
        episodes.sort(key=lambda e: e.created_at, reverse=True)
        return episodes[:limit]

    def clear(self) -> None:
        with self._lock:
            self._episodes.clear()
            self._prefs = PlayerPreferences()


_store: MemoryStore | None = None
_store_lock = threading.Lock()


def get_memory_store() -> MemoryStore:
    """Return the process-wide memory store (singleton, resettable in tests)."""
    global _store
    with _store_lock:
        if _store is None:
            _store = InMemoryMemoryStore()
        return _store
