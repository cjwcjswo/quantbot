"""Backend doc §23 Phase 5: events list + severity derivation + filters."""

from __future__ import annotations

from packages.storage.models import BotEventRow
from tests.api.conftest import add_rows


async def test_list_and_severity(client, session_factory):
    await add_rows(
        session_factory,
        BotEventRow(type="POSITION_OPENED", symbol="BTCUSDT", message="ok"),
        BotEventRow(type="EMERGENCY_TPSL_FAILED", symbol="BTCUSDT", message="bad"),
    )
    data = (await client.get("/events")).json()["data"]
    sev = {e["type"]: e["severity"] for e in data["events"]}
    assert sev["EMERGENCY_TPSL_FAILED"] == "CRITICAL"
    assert sev["POSITION_OPENED"] == "INFO"


async def test_filter_by_type_and_symbol(client, session_factory):
    await add_rows(
        session_factory,
        BotEventRow(type="TPSL_SET", symbol="BTCUSDT"),
        BotEventRow(type="TPSL_SET", symbol="ETHUSDT"),
    )
    data = (await client.get(
        "/events", params={"event_type": "TPSL_SET", "symbol": "ETHUSDT"})).json()["data"]
    assert len(data["events"]) == 1
    assert data["events"][0]["symbol"] == "ETHUSDT"


async def test_filter_by_severity(client, session_factory):
    await add_rows(
        session_factory,
        BotEventRow(type="RISK_LOCKED", symbol="BTCUSDT"),
        BotEventRow(type="SIGNAL", symbol="BTCUSDT"),
    )
    data = (await client.get(
        "/events", params={"severity": "ERROR"})).json()["data"]
    assert all(e["severity"] == "ERROR" for e in data["events"])
    assert any(e["type"] == "RISK_LOCKED" for e in data["events"])
