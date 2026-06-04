"""Daily PnL + summary queries (backend doc §14.2, §25.8)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from apps.api.repositories.base import row_to_dict
from packages.storage.models import (
    BotEventRow,
    DailyEventSummaryRow,
    DailyManualInterventionSummaryRow,
    DailyPnlRow,
    DailySymbolPnlRow,
    ManualInterventionLogRow,
    PositionProtectionLogRow,
    TradeRow,
)


async def list_daily_pnl(session_factory: Any, *, limit: int = 90) -> list[dict]:
    async with session_factory() as s:
        rows = (await s.execute(
            select(DailyPnlRow).order_by(DailyPnlRow.day.desc()).limit(limit)
        )).scalars().all()
    return [row_to_dict(r) for r in rows]


async def daily_pnl_for(session_factory: Any, day: str) -> dict | None:
    async with session_factory() as s:
        row = (await s.execute(
            select(DailyPnlRow).where(DailyPnlRow.day == day).limit(1)
        )).scalar_one_or_none()
    return row_to_dict(row) if row else None


def _same_day(dt, day: str) -> bool:
    return dt is not None and dt.strftime("%Y-%m-%d") == day


async def daily_log(session_factory: Any, *, day: str, mode: str | None) -> dict:
    async with session_factory() as s:
        trades = [r for r in (await s.execute(select(TradeRow))).scalars().all()
                  if _same_day(r.closed_at or r.ts, day)
                  and (mode is None or r.mode == mode)]
        events = [r for r in (await s.execute(select(BotEventRow))).scalars().all()
                  if _same_day(r.ts, day)]
        manuals = [r for r in
                   (await s.execute(select(ManualInterventionLogRow))).scalars().all()
                   if _same_day(r.ts, day)]
        protection = [r for r in
                      (await s.execute(select(PositionProtectionLogRow))).scalars().all()
                      if _same_day(r.ts, day)]

    wins = sum(1 for t in trades if _num(t.net_pnl or t.realized_pnl) > 0)
    losses = sum(1 for t in trades if _num(t.net_pnl or t.realized_pnl) < 0)
    net = sum(_num(t.net_pnl or t.realized_pnl) for t in trades)
    realized = sum(_num(t.realized_pnl) for t in trades)
    fees = sum(_num(t.fees) for t in trades)
    tpsl_failed = sum(1 for e in events if e.type in ("TPSL_FAILED", "EMERGENCY_TPSL_FAILED"))
    emergency = sum(1 for e in events if e.type.startswith("EMERGENCY"))
    return {
        "date": day,
        "mode": mode,
        "summary": {
            "trade_count": len(trades),
            "win_count": wins,
            "loss_count": losses,
            "net_pnl": _fmt(net),
            "realized_pnl": _fmt(realized),
            "unrealized_pnl": "0",
            "fees": _fmt(fees),
            "max_drawdown": "0",
            "manual_intervention_count": len(manuals),
            "tpsl_failed_count": tpsl_failed,
            "emergency_count": emergency,
        },
        "sections": {
            "trades": [row_to_dict(t) for t in trades],
            "events": [row_to_dict(e) for e in events],
            "manual_interventions": [row_to_dict(m) for m in manuals],
            "risk_events": [row_to_dict(e) for e in events
                            if e.type.startswith("RISK") or e.type.startswith("KILL")],
            "protection_events": [row_to_dict(p) for p in protection],
        },
    }


async def calendar(session_factory: Any, *, year: int, month: int, mode: str | None) -> dict:
    prefix = f"{year:04d}-{month:02d}"
    async with session_factory() as s:
        pnl = [r for r in (await s.execute(select(DailyPnlRow))).scalars().all()
               if r.day.startswith(prefix)]
        ev_sum = [r for r in (await s.execute(select(DailyEventSummaryRow))).scalars().all()
                  if r.day.startswith(prefix) and (mode is None or r.mode == mode)]
        mi_sum = [r for r in
                  (await s.execute(select(DailyManualInterventionSummaryRow))).scalars().all()
                  if r.day.startswith(prefix) and (mode is None or r.mode == mode)]
        sym = [r for r in (await s.execute(select(DailySymbolPnlRow))).scalars().all()
               if r.day.startswith(prefix) and (mode is None or r.mode == mode)]

    ev_by_day = {r.day: r for r in ev_sum}
    mi_by_day = {r.day: r.count for r in mi_sum}
    count_by_day: dict[str, int] = {}
    for r in sym:
        count_by_day[r.day] = count_by_day.get(r.day, 0) + r.trade_count

    by_date: dict[str, dict] = {}
    for r in sorted(pnl, key=lambda x: x.day):
        es = ev_by_day.get(r.day)
        by_date[r.day] = {
            "date": r.day,
            "trade_count": count_by_day.get(r.day, 0),
            "net_pnl": r.net,
            "has_warning": bool(es and es.warning_count > 0),
            "has_error": bool(es and (es.error_count > 0 or es.critical_count > 0)),
            "manual_intervention_count": mi_by_day.get(r.day, 0),
        }

    # Today's summary tables are not produced until the 00:05 KST job runs, so
    # compute today's entry live from raw rows (§25.6 cadence) if it falls in-month.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if today.startswith(prefix):
        by_date[today] = await _live_calendar_item(session_factory, today, mode)

    items = [by_date[d] for d in sorted(by_date)]
    return {"year": year, "month": month, "items": items}


async def _live_calendar_item(session_factory: Any, day: str, mode: str | None) -> dict:
    log = await daily_log(session_factory, day=day, mode=mode)
    s = log["summary"]
    events = log["sections"]["events"]
    has_warning = any(e.get("severity") == "WARNING" for e in events)
    has_error = any(e.get("severity") in ("ERROR", "CRITICAL") for e in events)
    return {
        "date": day,
        "trade_count": s["trade_count"],
        "net_pnl": s["net_pnl"],
        "has_warning": has_warning or s["tpsl_failed_count"] > 0,
        "has_error": has_error or s["emergency_count"] > 0,
        "manual_intervention_count": s["manual_intervention_count"],
    }


def _num(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _fmt(v: float) -> str:
    return f"{v:.2f}"
