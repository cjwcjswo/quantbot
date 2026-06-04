"""Backend doc §23 Phase 1: API basics, envelope, error format."""

from __future__ import annotations


async def test_health_ok(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["error"] is None
    assert body["data"]["status"] == "OK"
    assert body["data"]["postgres"] == "UP"
    assert body["data"]["redis"] == "UP"


async def test_not_found_envelope(client):
    # unknown trade -> NOT_FOUND error envelope
    r = await client.get("/trades/does-not-exist")
    assert r.status_code == 404
    body = r.json()
    assert body["ok"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "NOT_FOUND"
