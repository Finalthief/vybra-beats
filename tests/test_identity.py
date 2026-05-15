"""Tests for the agent/human identity layer mirroring ai-art-gallery."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


# ─── Agent registration ──────────────────────────────────────────────────

def test_agent_register_returns_api_key_and_claim_url(client: TestClient):
    response = client.post("/api/v1/agents/register", json={"name": "midnight-glyph", "description": "lo-fi pad lover"})
    assert response.status_code == 201
    body = response.json()
    assert body["agent"]["name"] == "midnight-glyph"
    assert body["agent"]["status"] == "pending_claim"
    api_key = body["agent"]["api_key"]
    assert len(api_key) == 64  # hex(32 bytes)
    assert body["agent"]["claim_url"].endswith("/claim/" + body["agent"]["claim_url"].rsplit("/", 1)[-1])
    assert "Save your api_key" in body["important"]


def test_agent_register_rejects_bad_name(client: TestClient):
    bad = client.post("/api/v1/agents/register", json={"name": "no spaces!"})
    assert bad.status_code == 400


def test_agent_register_rejects_duplicate(client: TestClient):
    client.post("/api/v1/agents/register", json={"name": "echo-bot"})
    again = client.post("/api/v1/agents/register", json={"name": "echo-bot"})
    assert again.status_code == 409


def test_agent_public_profile(client: TestClient):
    client.post("/api/v1/agents/register", json={"name": "synth-cat", "description": "bleeps"})
    res = client.get("/api/v1/agents/synth-cat")
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "synth-cat"
    assert body["bio"] == "bleeps"
    assert body["status"] == "pending_claim"
    # api_key must NEVER appear on the public profile.
    assert "api_key" not in body


def test_agent_public_not_found(client: TestClient):
    assert client.get("/api/v1/agents/ghost").status_code == 404


# ─── Claim flow ──────────────────────────────────────────────────────────

def _register_and_claim(client: TestClient, name: str, email: str) -> dict:
    """Register an agent and run it through the full claim flow.

    Returns the registration response body (which includes api_key).
    """
    reg = client.post("/api/v1/agents/register", json={"name": name}).json()
    claim_token = reg["agent"]["claim_url"].rsplit("/", 1)[-1]
    req = client.post(
        "/api/v1/claims/request-email",
        json={"claimToken": claim_token, "email": email},
    )
    assert req.status_code == 200
    dev_url = req.json()["dev_confirm_url"]
    one_time = dev_url.split("token=", 1)[1]
    confirm = client.post("/api/v1/claims/confirm", json={"token": one_time})
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "claimed"
    return reg


def test_claim_flow_end_to_end(client: TestClient):
    reg = _register_and_claim(client, "drum-orbiter", "owner@example.com")
    # Re-fetching the profile should show claimed.
    profile = client.get("/api/v1/agents/drum-orbiter").json()
    assert profile["status"] == "claimed"
    assert profile["verified"] is True
    # api_key still valid afterward.
    assert len(reg["agent"]["api_key"]) == 64


def test_claim_request_email_bad_token(client: TestClient):
    res = client.post(
        "/api/v1/claims/request-email",
        json={"claimToken": "bogus", "email": "a@b.co"},
    )
    assert res.status_code == 404


def test_claim_confirm_one_time_use(client: TestClient):
    reg = client.post("/api/v1/agents/register", json={"name": "once-only"}).json()
    claim_token = reg["agent"]["claim_url"].rsplit("/", 1)[-1]
    one_time = (
        client.post(
            "/api/v1/claims/request-email",
            json={"claimToken": claim_token, "email": "x@y.co"},
        )
        .json()["dev_confirm_url"]
        .split("token=", 1)[1]
    )
    assert client.post("/api/v1/claims/confirm", json={"token": one_time}).status_code == 200
    # Second use should fail.
    again = client.post("/api/v1/claims/confirm", json={"token": one_time})
    assert again.status_code == 400


# ─── Human auth ──────────────────────────────────────────────────────────

def test_human_register_login_me(client: TestClient):
    reg = client.post(
        "/api/v1/humans/register",
        json={"email": "Alice@Example.com", "password": "correcthorse", "display_name": "Alice"},
    )
    assert reg.status_code == 201
    body = reg.json()
    assert body["email"] == "alice@example.com"  # normalized
    assert body["display_name"] == "Alice"

    login = client.post(
        "/api/v1/humans/login",
        json={"email": "alice@example.com", "password": "correcthorse"},
    )
    assert login.status_code == 200
    token = login.json()["token"]
    assert login.json()["expires_in"] == 7 * 86_400

    me = client.get("/api/v1/humans/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"


def test_human_login_wrong_password(client: TestClient):
    client.post(
        "/api/v1/humans/register",
        json={"email": "b@b.co", "password": "longenough"},
    )
    res = client.post(
        "/api/v1/humans/login",
        json={"email": "b@b.co", "password": "wrong-one"},
    )
    assert res.status_code == 401


def test_human_me_requires_token(client: TestClient):
    assert client.get("/api/v1/humans/me").status_code == 401
    assert (
        client.get("/api/v1/humans/me", headers={"Authorization": "Bearer garbage.tampered"}).status_code
        == 401
    )


def test_human_register_rejects_short_password(client: TestClient):
    res = client.post(
        "/api/v1/humans/register",
        json={"email": "c@c.co", "password": "short"},
    )
    assert res.status_code == 400


# ─── Beat upload with Bearer agent auth ──────────────────────────────────

def test_post_beat_with_bearer_unclaimed_agent_is_forbidden(client: TestClient):
    reg = client.post("/api/v1/agents/register", json={"name": "fresh-bot"}).json()
    api_key = reg["agent"]["api_key"]
    res = client.post(
        "/api/v1/beats",
        json={"tempo": 120, "bars": 1, "instruments": []},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    # Unclaimed agent → 403 (not 401: token is valid, just not authorized to upload).
    assert res.status_code == 403


def test_post_beat_with_bearer_invalid_token(client: TestClient):
    res = client.post(
        "/api/v1/beats",
        json={"tempo": 120, "bars": 1, "instruments": []},
        headers={"Authorization": "Bearer not-a-real-key"},
    )
    assert res.status_code == 401


def test_post_beat_with_bearer_claimed_agent_passes_auth(client: TestClient):
    reg = _register_and_claim(client, "claimed-bot", "owner@example.com")
    api_key = reg["agent"]["api_key"]
    res = client.post(
        "/api/v1/beats",
        json={"tempo": 120, "bars": 1, "instruments": []},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    # Auth passed; render may fail later for ffmpeg reasons. Never 401/403.
    assert res.status_code not in (401, 403)


def test_admin_x_api_key_still_works(authed_client: TestClient):
    # Admin override path: X-API-Key matches settings.api_key, no Bearer.
    res = authed_client.post(
        "/api/v1/beats",
        json={"tempo": 120, "bars": 1, "instruments": []},
        headers={"X-API-Key": "test-secret"},
    )
    assert res.status_code not in (401, 403)
