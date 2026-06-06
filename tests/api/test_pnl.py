"""Backend doc §23 Phase 5: pnl summary + daily."""

from __future__ import annotations

import json

from packages.storage.models import (
    DailyAccountEquityRow,
    DailyPnlRow,
    PaperAccountSnapshotRow,
)
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


async def test_summary_prefers_daily_equity_fields_from_redis(client, redis):
    await redis.set("bot:mode", "LIVE")
    await redis.set("bot:pnl", json.dumps({
        "realized": "0",
        "unrealized": "0",
        "fees": "0",
        "equity": "10020",
        "start_equity": "10000",
        "daily_net_pnl": "20",
        "daily_net_pnl_percent": "0.2",
        "max_drawdown_today": "0.1",
    }))
    data = (await client.get("/pnl/summary")).json()["data"]
    assert data["start_equity"] == "10000"
    assert data["daily_net_pnl"] == "20.00"
    assert data["daily_net_pnl_percent"] == "0.2"


async def test_summary_enriches_old_redis_payload_with_daily_equity(
    client, redis, session_factory,
):
    await redis.set("bot:mode", "LIVE")
    await redis.set("bot:pnl", json.dumps({
        "realized": "0",
        "unrealized": "0",
        "fees": "0",
        "equity": "10075",
    }))
    await add_rows(session_factory, DailyAccountEquityRow(
        day="2026-06-04",
        mode="LIVE",
        start_equity="10000",
        current_equity="10050",
        peak_equity="10080",
        net_pnl="50",
        net_pnl_percent="0.5",
        max_drawdown_percent="0.3",
    ))
    data = (await client.get("/pnl/summary")).json()["data"]
    assert data["start_equity"] == "10000"
    assert data["daily_net_pnl"] == "75.00"
    assert data["daily_net_pnl_percent"] == "0.75"


async def test_summary_fallback_to_db(client, session_factory):
    await add_rows(session_factory, DailyPnlRow(
        day="2026-06-04", realized="10", unrealized="0", fees="1", net="9"))
    data = (await client.get("/pnl/summary")).json()["data"]
    assert data["degraded"] is True
    assert data["realized_pnl"] == "10.00"


async def test_summary_fallback_to_daily_equity(client, session_factory):
    await add_rows(session_factory, DailyAccountEquityRow(
        day="2026-06-04",
        mode="LIVE",
        start_equity="10000",
        current_equity="10050",
        peak_equity="10080",
        wallet_balance="10040",
        unrealized_pnl="10",
        realized_pnl="40",
        fees="2",
        funding_fees="0",
        net_pnl="50",
        net_pnl_percent="0.5",
        max_drawdown_percent="0.3",
    ))
    data = (await client.get("/pnl/summary")).json()["data"]
    assert data["degraded"] is True
    assert data["equity"] == "10050"
    assert data["start_equity"] == "10000"
    assert data["daily_net_pnl"] == "50.00"


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


async def test_daily_list_prefers_equity_baseline_rows(client, session_factory):
    await add_rows(
        session_factory,
        DailyPnlRow(
            day="2026-06-03", realized="7", unrealized="0", fees="1", net="6",
        ),
        DailyPnlRow(
            day="2026-06-04", realized="9", unrealized="0", fees="1", net="8",
        ),
        DailyAccountEquityRow(
            day="2026-06-04",
            mode="LIVE",
            start_equity="10000",
            current_equity="10050",
            peak_equity="10080",
            net_pnl="50",
            net_pnl_percent="0.5",
            max_drawdown_percent="0.3",
        ),
    )
    data = (await client.get("/pnl/daily")).json()["data"]
    assert [row["day"] for row in data["daily"]] == ["2026-06-04", "2026-06-03"]
    row = data["daily"][0]
    assert row["start_equity"] == "10000"
    assert row["current_equity"] == "10050"
    assert row["net"] == "50"


async def test_monthly_pnl(client, session_factory):
    await add_rows(
        session_factory,
        DailyAccountEquityRow(
            day="2026-06-01",
            mode="LIVE",
            start_equity="10000",
            current_equity="10020",
            peak_equity="10020",
            net_pnl="20",
            net_pnl_percent="0.2",
            max_drawdown_percent="0",
        ),
        DailyAccountEquityRow(
            day="2026-06-02",
            mode="LIVE",
            start_equity="10020",
            current_equity="10050",
            peak_equity="10060",
            net_pnl="30",
            net_pnl_percent="0.2994",
            max_drawdown_percent="0.1",
        ),
    )
    data = (await client.get("/pnl/monthly")).json()["data"]
    assert data["monthly"][0]["month"] == "2026-06"
    assert data["monthly"][0]["net_pnl"] == "50.00"
