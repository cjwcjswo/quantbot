"""Backend doc §25.8/§25.11: daily log + calendar."""

from __future__ import annotations

from datetime import datetime, timezone

from packages.storage.models import (
    DailyEventSummaryRow,
    DailyPnlRow,
    DailySymbolPnlRow,
    TradeRow,
)
from tests.api.conftest import add_rows


async def test_daily_log(client, session_factory):
    day_dt = datetime(2026, 6, 4, 12, tzinfo=timezone.utc)
    await add_rows(
        session_factory,
        TradeRow(trade_id="t1", symbol="BTCUSDT", side="LONG", qty="0.01",
                 entry_price="65000", exit_price="67000", realized_pnl="20",
                 net_pnl="18", mode="PAPER", closed_at=day_dt),
        TradeRow(trade_id="t2", symbol="ETHUSDT", side="SHORT", qty="1",
                 entry_price="2000", exit_price="2050", realized_pnl="-30",
                 net_pnl="-32", mode="PAPER", closed_at=day_dt),
    )
    data = (await client.get(
        "/logs/daily", params={"date": "2026-06-04", "mode": "PAPER"})).json()["data"]
    assert data["summary"]["trade_count"] == 2
    assert data["summary"]["win_count"] == 1
    assert data["summary"]["loss_count"] == 1


async def test_daily_log_bad_date(client):
    r = await client.get("/logs/daily", params={"date": "06-04-2026"})
    assert r.status_code == 422


async def test_calendar_from_summary(client, session_factory):
    # use a past day (not today) so the live-today override does not apply
    await add_rows(
        session_factory,
        DailyPnlRow(day="2026-05-10", realized="20", unrealized="0", fees="2", net="18"),
        DailySymbolPnlRow(day="2026-05-10", mode="PAPER", symbol="BTCUSDT",
                          trade_count=3, net="18"),
        DailyEventSummaryRow(day="2026-05-10", mode="PAPER", warning_count=1),
    )
    data = (await client.get(
        "/logs/daily/calendar",
        params={"year": 2026, "month": 5, "mode": "PAPER"})).json()["data"]
    item = next(i for i in data["items"] if i["date"] == "2026-05-10")
    assert item["trade_count"] == 3
    assert item["has_warning"] is True


async def test_calendar_includes_live_today(client, session_factory):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    await add_rows(session_factory, TradeRow(
        trade_id="t-today", symbol="BTCUSDT", side="LONG", qty="0.01",
        entry_price="65000", exit_price="67000", realized_pnl="20", net_pnl="18",
        mode="PAPER", closed_at=now))
    data = (await client.get(
        "/logs/daily/calendar",
        params={"year": now.year, "month": now.month, "mode": "PAPER"})).json()["data"]
    today = now.strftime("%Y-%m-%d")
    item = next(i for i in data["items"] if i["date"] == today)
    assert item["trade_count"] >= 1
