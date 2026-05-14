from __future__ import annotations

import pytest

from src.storage import BeatNotFoundError, LocalBeatStorage


def _write_assets(storage: LocalBeatStorage, beat_id: str) -> None:
    for ext in ("mid", "wav", "mp3"):
        storage.asset_path(beat_id, ext).write_bytes(b"\x00")


def test_save_and_load_round_trip(storage: LocalBeatStorage):
    beat_id = "abc12345"
    _write_assets(storage, beat_id)
    render_result = {
        "id": beat_id,
        "tempo": 128,
        "bars": 4,
        "duration": 7.5,
        "total_notes": 32,
        "instruments": 2,
        "title": "Test Beat",
        "agent_name": "tester",
        "genre": "hip-hop",
        "tags": ["drums", "bass"],
        "builds_on": [],
    }
    response = storage.save_render_result(render_result, is_chiptune=False)
    assert response.id == beat_id
    assert response.title == "Test Beat"
    assert response.download_urls.mp3 == f"/data/{beat_id}.mp3"

    loaded = storage.load_metadata(beat_id)
    assert loaded.id == beat_id
    assert loaded.title == "Test Beat"
    assert loaded.tags == ["drums", "bass"]
    assert loaded.download_urls.wav == f"/data/{beat_id}.wav"


def test_load_metadata_missing_raises(storage: LocalBeatStorage):
    with pytest.raises(BeatNotFoundError):
        storage.load_metadata("does-not-exist")


def test_save_render_result_missing_asset_raises(storage: LocalBeatStorage):
    render_result = {
        "id": "missing01",
        "tempo": 120,
        "bars": 4,
        "duration": 8.0,
        "total_notes": 0,
        "instruments": 0,
    }
    with pytest.raises(RuntimeError, match="Missing rendered asset"):
        storage.save_render_result(render_result)


def test_list_metadata_paginates_newest_first(storage: LocalBeatStorage):
    import time

    ids = ["beat_a", "beat_b", "beat_c"]
    for beat_id in ids:
        _write_assets(storage, beat_id)
        storage.save_render_result({
            "id": beat_id,
            "tempo": 120,
            "bars": 1,
            "duration": 2.0,
            "total_notes": 0,
            "instruments": 0,
        })
        time.sleep(0.01)  # ensure distinct mtimes

    items, total = storage.list_metadata(limit=2, offset=0)
    assert total == 3
    assert len(items) == 2
    # newest first
    assert items[0].id == "beat_c"
    assert items[1].id == "beat_b"

    items, total = storage.list_metadata(limit=2, offset=2)
    assert total == 3
    assert [i.id for i in items] == ["beat_a"]
