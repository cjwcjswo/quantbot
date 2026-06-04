"""Backend doc §23 Phase 5: pnl summary + daily."""

from __future__ import annotations

import json

from packages.storage.models import DailyPnlRow, PaperAccountSnapshotRow
from tests.api.conftest import add_rows


async def test_summary_from_redis(client, redis):
    await redis.set("bot:mode", "PAPER")
    await redis.set("bot:pnl", json.dumps({
        "realized": "30", "unrealized": "20", "fees": "2", "funding_fees": "0",
        "equity": "10050"}))
    data = (await client.get("/pnl/summary")).json()["data"]
    # daily_net = 30 + 20 - 2 - 0 = 48
    assert data["daily_net_pnl"] == "48.00"
    assert data["equity"] == "10050"


async def test_summary_fallback_to_db(client, session_factory):
    await add_rows(session_factory, DailyPnlRow(
        day="2026-06-04", realized="10", unrealized="0", fees="1", net="9"))
    data = (await client.get("/pnl/summary")).json()["data"]
    assert data["degraded"] is True
    assert data["realized_pnl"] == "10.00"


async def test_summary_equity_from_paper_snapshot(client, redis, session_factory):
    # bot:pnl has no equity; PAPER equity comes from paper_account_snapshots
    await redis.set("bot:mode", "PAPER")
    await redis.set("bot:pnl", json.dumps({"realized": "5", "unrealized": "0", "fees": "0"}))
    await add_rows(session_factory, PaperAccountSnapshotRow(
        equity="10120.50", balance="10100", unrealized_pnl="20.50"))
    data = (await client.get("/pnl/summary")).json()["data"]
    assert data["equity"] == "10120.50"


async def test_daily_list(client, session_factory):
    await add_rows(session_factory, DailyPnlRow(
        day="2026-06-04", realized="10", unrealized="0", fees="1", net="9"))
    data = (await client.get("/pnl/daily")).json()["data"]
    assert len(data["daily"]) == 1
