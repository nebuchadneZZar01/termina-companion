"""Save/load snapshots persist and reload the UI game state."""

import pytest

from app.save import DEFAULT_SAVE_NAME, SaveSnapshot, get_save_path, load_state, save_state


@pytest.fixture(autouse=True)
def _save_dir(tmp_path, monkeypatch):
    """Point the save directory inside pytest's tmp_path."""
    monkeypatch.setenv("RAG_QDRANT_PATH", str(tmp_path / "cache" / "qdrant"))


def _payload() -> dict:
    return {
        "version": 1,
        "day": 2,
        "time": {"day": 2, "hour": 9, "minute": 30},
        "location": "North Clock Town",
        "masks": ["Keaton Mask"],
        "inventory": ["Kafei's Letter"],
        "quest_progress": ["human_girl"],
        "goal": "Reunite Anju and Kafei",
    }


def test_save_and_load_round_trip():
    """A dict saved to disk reloads with every field intact."""
    path = save_state(_payload())
    assert path.exists()

    snapshot = load_state()
    assert snapshot is not None
    assert snapshot.day == 2
    assert snapshot.time.hour == 9
    assert snapshot.time.minute == 30
    assert snapshot.location == "North Clock Town"
    assert snapshot.masks == ["Keaton Mask"]
    assert snapshot.inventory == ["Kafei's Letter"]
    assert snapshot.quest_progress == ["human_girl"]
    assert snapshot.goal == "Reunite Anju and Kafei"


def test_save_accepts_snapshot_model():
    """A SaveSnapshot instance is written as-is."""
    snap = SaveSnapshot(time={"day": 1, "hour": 6, "minute": 0}, goal="")
    path = save_state(snap)
    loaded = load_state()
    assert loaded is not None
    assert loaded.model_dump(exclude_none=True) == snap.model_dump(exclude_none=True)
    assert path.name == DEFAULT_SAVE_NAME


def test_load_missing_file_returns_none():
    """No save on disk means load_state returns None, not an error."""
    assert load_state() is None


def test_load_invalid_json_returns_none():
    """A corrupt save file degrades to None instead of raising."""
    path = get_save_path()
    path.write_text("{not json", encoding="utf-8")
    assert load_state() is None
