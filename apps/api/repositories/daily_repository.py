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
    no_entry = [e for e in events if e.type == "NO_ENTRY_REASON"]
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
            "no_entry_count": len(no_entry),
            "top_no_entry_reasons": _top_counts(
                [((e.data or {}).get("reason_code") or e.message or "UNKNOWN")
                 for e in no_entry],
                limit=10,
            ),
        },
        "sections": {
            "trades": [row_to_dict(t) for t in trades],
            "events": [row_to_dict(e) for e in events],
            "manual_interventions": [row_to_dict(m) for m in manuals],
            "risk_events": [row_to_dict(e) for e in events
                            if e.type.startswith("RISK") or e.type.startswith("KILL")],
            "protection_events": [row_to_dict(p) for p in protection],
            "no_entry_summary": _no_entry_summary(no_entry),
            "entry_mode_performance": _entry_mode_performance(trades),
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


def _top_counts(values: list[str], *, limit: int | None = None) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    items = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    if limit is not None:
        items = items[:limit]
    return dict(items)


def _no_entry_summary(events: list[BotEventRow]) -> dict:
    reasons: list[str] = []
    symbols: list[str] = []
    modes: list[str] = []
    stages: list[str] = []
    for event in events:
        data = event.data or {}
        reasons.append(str(data.get("reason_code") or event.message or "UNKNOWN"))
        if event.symbol:
            symbols.append(event.symbol)
        modes.append(str(data.get("entry_mode_candidate") or "UNKNOWN"))
        stages.append(str(data.get("failed_stage") or "UNKNOWN"))
    return {
        "by_reason_code": _top_counts(reasons),
        "by_symbol": _top_counts(symbols),
        "by_entry_mode": _top_counts(modes),
        "by_failed_stage": _top_counts(stages),
        "top_blocking_guard": _top_counts(stages, limit=1),
        "relaxation_candidates": _relaxation_candidates(reasons, stages),
    }


def _relaxation_candidates(reasons: list[str], stages: list[str]) -> list[dict]:
    counts = _top_counts(reasons)
    stage_counts = _top_counts(stages)
    suggestions = {
        "VOLUME_TOO_LOW": "volume.min_setup_volume_ratio or entry volume threshold",
        "BREAKOUT_VOLUME_TOO_LOW": "volume.min_breakout_volume_ratio",
        "BODY_TOO_SMALL": "candle_quality.min_body_ratio_for_breakout",
        "OPPOSITE_WICK_TOO_LARGE": "candle_quality.max_opposite_wick_ratio_for_breakout",
        "WEAK_CLOSE_IN_RANGE": "candle_quality close-position threshold",
        "BREAKOUT_NOT_HEALTHY": "breakout volume, candle quality, or anti-chase thresholds",
        "BREAKOUT_EXHAUSTION": "entry.anti_chase.exhaustion_volume_ratio",
        "ANTI_CHASE_LONG": "entry.anti_chase long-side thresholds",
        "ANTI_CHASE_SHORT": "entry.anti_chase short-side thresholds",
        "SCOUT_SCORE_TOO_LOW": "entry.pre_breakout.min_score",
        "SCOUT_SCORE_TOO_LOW_NO_COMPRESSION": (
            "entry.pre_breakout.no_compression_min_score or no_compression_position_fraction"
        ),
        "SCOUT_TOO_FAR_FROM_BOX": "entry.pre_breakout.max_distance_to_box_atr",
        "RETEST_TOO_FAR_FROM_LEVEL": "entry.retest_confirm.retest_tolerance_atr",
        "RISK_REJECTED": "risk limits and open position exposure",
        "PRE_ORDER_INSUFFICIENT_DEPTH": "orders.pre_order_depth_multiple or scanner depth filter",
        "COOLDOWN_ACTIVE": "cooldown settings",
    }
    rows: list[dict] = []
    for reason, count in sorted(counts.items(), key=lambda item: item[1], reverse=True):
        target = suggestions.get(reason)
        if target is None:
            continue
        rows.append({"reason_code": reason, "count": count, "candidate": target})
        if len(rows) >= 5:
            break
    if rows:
        return rows
    return [
        {"failed_stage": stage, "count": count, "candidate": "review this guard first"}
        for stage, count in list(stage_counts.items())[:5]
    ]


def _entry_mode_performance(trades: list[TradeRow]) -> list[dict]:
    by_mode: dict[str, dict] = {}
    for trade in trades:
        mode = trade.entry_mode or "UNKNOWN"
        row = by_mode.setdefault(
            mode,
            {
                "entry_mode": mode,
                "trade_count": 0,
                "win_count": 0,
                "loss_count": 0,
                "net_pnl": 0.0,
                "r_total": 0.0,
                "r_count": 0,
            },
        )
        pnl = _num(trade.net_pnl or trade.realized_pnl)
        row["trade_count"] += 1
        row["win_count"] += 1 if pnl > 0 else 0
        row["loss_count"] += 1 if pnl < 0 else 0
        row["net_pnl"] += pnl
        r = _num(trade.r_multiple)
        if trade.r_multiple is not None:
            row["r_total"] += r
            row["r_count"] += 1
    out = []
    for row in by_mode.values():
        trades_count = row["trade_count"]
        avg_r = row["r_total"] / row["r_count"] if row["r_count"] else 0.0
        out.append({
            "entry_mode": row["entry_mode"],
            "trade_count": trades_count,
            "win_count": row["win_count"],
            "loss_count": row["loss_count"],
            "win_rate": _fmt(row["win_count"] / trades_count * 100) if trades_count else "0.00",
            "net_pnl": _fmt(row["net_pnl"]),
            "avg_r": _fmt(avg_r),
        })
    return sorted(out, key=lambda row: row["trade_count"], reverse=True)
