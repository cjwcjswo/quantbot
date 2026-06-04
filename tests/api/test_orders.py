"""Backend doc §23 Phase 4: orders list + cancel."""

from __future__ import annotations

from packages.storage.models import OrderRow
from tests.api.conftest import add_rows


async def test_list_orders_and_filter(client, session_factory):
    await add_rows(
        session_factory,
        OrderRow(symbol="BTCUSDT", side="Buy", order_type="LIMIT", qty="0.01",
                 status="FILLED", source="BOT", mode="PAPER", order_id="o1"),
        OrderRow(symbol="ETHUSDT", side="Sell", order_type="MARKET", qty="1",
                 status="NEW", source="BOT", mode="PAPER", order_id="o2"),
    )
    data = (await client.get("/orders")).json()["data"]
    assert len(data["orders"]) == 2
    data = (await client.get("/orders", params={"status": "NEW"})).json()["data"]
    assert len(data["orders"]) == 1
    assert data["orders"][0]["order_id"] == "o2"


async def test_invalid_status(client):
    r = await client.get("/orders", params={"status": "BOGUS"})
    assert r.status_code == 422


async def test_cancel_order(client, session_factory):
    await add_rows(session_factory, OrderRow(
        symbol="BTCUSDT", side="Buy", order_type="LIMIT", qty="0.01",
        status="NEW", order_id="abc"))
    r = await client.post("/orders/abc/cancel", json={})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "PENDING"


async def test_cancel_filled_order_rejected(client, session_factory):
    await add_rows(session_factory, OrderRow(
        symbol="BTCUSDT", side="Buy", order_type="LIMIT", qty="0.01",
        status="FILLED", order_id="filled"))
    r = await client.post("/orders/filled/cancel", json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "BOT_COMMAND_REJECTED"


async def test_cancel_unknown_order(client):
    r = await client.post("/orders/nope/cancel", json={})
    assert r.status_code == 404
