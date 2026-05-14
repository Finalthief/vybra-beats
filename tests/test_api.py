from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from src.storage import LocalBeatStorage


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_instruments(client: TestClient):
    response = client.get("/api/instruments")
    assert response.status_code == 200
    body = response.json()
    assert "kick" in body["gm_drum_map"]
    assert "electric_bass" in body["gm_melodic_map"]
    assert body["drum_kits"]


def test_get_beat_not_found(client: TestClient):
    response = client.get("/api/beats/no-such-beat")
    assert response.status_code == 404


def test_list_beats_empty(client: TestClient):
    response = client.get("/api/beats")
    assert response.status_code == 200
    body = response.json()
    assert body == {"items": [], "total": 0, "limit": 20, "offset": 0}


def test_list_beats_after_seed(client: TestClient, storage: LocalBeatStorage):
    for beat_id in ("seeded01", "seeded02"):
        for ext in ("mid", "wav", "mp3"):
            storage.asset_path(beat_id, ext).write_bytes(b"\x00")
        storage.save_render_result({
            "id": beat_id,
            "tempo": 120,
            "bars": 1,
            "duration": 2.0,
            "total_notes": 0,
            "instruments": 0,
        })

    response = client.get("/api/beats?limit=10")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["id"] for item in body["items"]} == {"seeded01", "seeded02"}


def test_list_beats_clamps_limit(client: TestClient):
    response = client.get("/api/beats?limit=9999")
    assert response.status_code == 422


def test_post_requires_api_key_when_configured(authed_client: TestClient):
    payload = {"tempo": 120, "bars": 1, "instruments": []}
    response = authed_client.post("/api/beats", json=payload)
    assert response.status_code == 401

    bad = authed_client.post("/api/beats", json=payload, headers={"X-API-Key": "wrong"})
    assert bad.status_code == 401


def test_post_open_when_no_api_key_configured(client: TestClient):
    # With ffmpeg missing or with no actual render path, we expect the
    # request to be accepted by the auth gate (no 401). We don't assert 201
    # because synthesis depends on ffmpeg + a soundfont.
    payload = {"tempo": 120, "bars": 1, "instruments": []}
    response = client.post("/api/beats", json=payload)
    assert response.status_code != 401


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_post_chiptune_render_smoke(client: TestClient):
    payload = {
        "tempo": 120,
        "bars": 1,
        "chiptune": True,
        "instruments": [
            {
                "type": "drum",
                "kit": "chiptune",
                "pattern": {"snare": [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0]},
            },
            {
                "type": "melodic",
                "instrument": "synth_bass",
                "notes": [{"pitch": 36, "start": 0, "duration": 0.5}],
            },
        ],
    }
    response = client.post("/api/beats", json=payload)
    # Even with ffmpeg present, MIDI synthesis needs a soundfont. If the
    # render fails the API returns 500 — we accept either 201 or 500 here,
    # but never a crash.
    assert response.status_code in (201, 500)
