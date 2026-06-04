"""Backend doc §23 Phase 6: strategy config get/patch."""

from __future__ import annotations

from packages.storage.models import PositionRow, StrategyConfigRow
from tests.api.conftest import add_rows


async def test_get_default_config(client):
    data = (await client.get("/strategy/config")).json()["data"]
    assert data["config_version"] == 0
    assert "trend_following" in data["strategy"]["active_strategies"]
    # with no DB override, risk/entry/orders reflect the running quantbot.yaml
    assert isinstance(data["risk"], dict) and len(data["risk"]) > 0
    assert len(data["orders"]) > 0
    assert len(data["tpsl"]) > 0
    assert len(data["funding_guard"]) > 0


async def test_patch_creates_version_and_reloads(client, redis, session_factory):
    await add_rows(session_factory, StrategyConfigRow(
        name="active", enabled=True, config={"risk": {}}, version=1, mode="PAPER"))
    r = await client.put("/strategy/config", json={
        "config_version": 1, "patch": {"entry": {"enabled_modes": ["scout"]}},
        "reason": "tune"})
    assert r.status_code == 200
    assert r.json()["data"]["config_version"] == 2
    q = await redis.lrange("commands:bot", 0, -1)
    assert "RELOAD_CONFIG" in q[0]


async def test_patch_accepts_extended_config_section(client, redis, session_factory):
    await add_rows(session_factory, StrategyConfigRow(
        name="active", enabled=True, config={}, version=1, mode="PAPER"))
    r = await client.put("/strategy/config", json={
        "config_version": 1,
        "patch": {"scanner": {"max_candidates": 10}},
        "reason": "reduce watchlist"})
    assert r.status_code == 200
    assert r.json()["data"]["config_version"] == 2


async def test_patch_version_conflict(client, session_factory):
    await add_rows(session_factory, StrategyConfigRow(
        name="active", config={}, version=5))
    r = await client.put("/strategy/config", json={
        "config_version": 1, "patch": {"entry": {}}, "reason": "x"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CONFLICT"


async def test_patch_forbidden_with_open_position(client, session_factory):
    await add_rows(
        session_factory,
        StrategyConfigRow(name="active", config={}, version=1),
        PositionRow(symbol="BTCUSDT", side="LONG", status="ACTIVE", source="BOT",
                    qty="0.01", avg_entry_price="65000"),
    )
    r = await client.put("/strategy/config", json={
        "config_version": 1, "patch": {"risk": {"max_leverage": 10}}, "reason": "x"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"


async def test_patch_unknown_field(client, session_factory):
    await add_rows(session_factory, StrategyConfigRow(
        name="active", config={}, version=1))
    r = await client.put("/strategy/config", json={
        "config_version": 1, "patch": {"bogus": {}}, "reason": "x"})
    assert r.status_code == 422
