"""Backend doc §23 Phase 5 + §25.9: trades, fills, trade detail."""

from __future__ import annotations

from packages.storage.models import BotEventRow, FillRow, TradeRow
from tests.api.conftest import add_rows


async def test_list_trades_filter(client, session_factory):
    await add_rows(
        session_factory,
        TradeRow(trade_id="t1", symbol="BTCUSDT", side="LONG", qty="0.01",
                 entry_price="65000", exit_price="67000", realized_pnl="20",
                 net_pnl="18", strategy_id="trend_following", entry_mode="RETEST_CONFIRM",
                 mode="PAPER", r_multiple="2.0"),
        TradeRow(trade_id="t2", symbol="ETHUSDT", side="SHORT", qty="1",
                 entry_price="2000", exit_price="1950", realized_pnl="-50",
                 exit_reason="STOP_LOSS",
                 mode="PAPER", entry_mode="BREAKOUT_CONFIRM"),
    )
    data = (await client.get("/trades")).json()["data"]
    assert len(data["trades"]) == 2
    data = (await client.get(
        "/trades", params={"entry_mode": "RETEST_CONFIRM"})).json()["data"]
    assert len(data["trades"]) == 1
    assert data["trades"][0]["trade_id"] == "t1"
    assert data["trades"][0]["r_multiple"] == "2.0"
    data = (await client.get(
        "/trades", params={"pnl": "negative", "exit_reason": "STOP_LOSS"})).json()["data"]
    assert len(data["trades"]) == 1
    assert data["trades"][0]["trade_id"] == "t2"


async def test_list_trades_invalid_pnl_filter(client):
    r = await client.get("/trades", params={"pnl": "flat"})
    assert r.status_code == 422


async def test_list_fills(client, session_factory):
    await add_rows(session_factory, FillRow(
        symbol="BTCUSDT", order_id="o1", side="Buy", price="65000", qty="0.01",
        fee="0.5", mode="PAPER"))
    data = (await client.get("/fills")).json()["data"]
    assert len(data["fills"]) == 1


async def test_trade_detail_with_timeline(client, session_factory):
    await add_rows(
        session_factory,
        TradeRow(trade_id="t1", symbol="BTCUSDT", side="LONG", qty="0.01",
                 entry_price="65000", exit_price="67000", realized_pnl="20",
                 mode="PAPER"),
        BotEventRow(type="POSITION_OPENED", symbol="BTCUSDT", message="open",
                    data={"qty": "0.01"}),
        BotEventRow(type="POSITION_CLOSED", symbol="BTCUSDT", message="close"),
    )
    data = (await client.get("/trades/t1")).json()["data"]
    assert data["trade"]["trade_id"] == "t1"
    timeline_types = [e["type"] for e in data["timeline"]]
    assert "POSITION_OPENED" in timeline_types
    assert "POSITION_CLOSED" in timeline_types
    assert data["timeline"][0]["data"] == {"qty": "0.01"}


async def test_trade_detail_not_found(client):
    r = await client.get("/trades/missing")
    assert r.status_code == 404
