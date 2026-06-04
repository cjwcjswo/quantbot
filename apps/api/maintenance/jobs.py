"""Maintenance jobs: daily summary, archive, retention cleanup, health check (§25)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from apps.api.maintenance.retention_policy import RetentionPolicy
from packages.storage.models import (
    BotEventRow,
    BotEventsArchiveRow,
    DailyEntryModePnlRow,
    DailyEventSummaryRow,
    DailyManualInterventionSummaryRow,
    DailyPnlRow,
    DailyStrategyPnlRow,
    DailySymbolPnlRow,
    FillRow,
    FillsArchiveRow,
    ManualInterventionLogRow,
    OrderRow,
    OrdersArchiveRow,
    ReconciliationLogRow,
    ReconciliationLogsArchiveRow,
    RetentionStatusRow,
    TradeRow,
    TradesArchiveRow,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _yesterday_kst() -> str:
    kst = timezone(timedelta(hours=9))
    return (datetime.now(kst) - timedelta(days=1)).strftime("%Y-%m-%d")


def _day_of(dt: datetime | None, fallback: datetime) -> str:
    return (dt or fallback).strftime("%Y-%m-%d")


def _D(v: Any) -> Decimal:
    try:
        return Decimal(str(v)) if v is not None else Decimal(0)
    except Exception:  # noqa: BLE001
        return Decimal(0)


def _serialize(row: Any) -> dict:
    out: dict = {}
    for col in row.__table__.columns:
        val = getattr(row, col.name)
        out[col.name] = val.isoformat() if isinstance(val, datetime) else val
    return out


async def _touch_status(session: Any, **fields: Any) -> None:
    row = (await session.execute(select(RetentionStatusRow).limit(1))).scalar_one_or_none()
    if row is None:
        row = RetentionStatusRow()
        session.add(row)
    for k, v in fields.items():
        setattr(row, k, v)


# --------------------------------------------------------------------------- #
# daily summary (00:05 KST)
# --------------------------------------------------------------------------- #
async def daily_summary(
    session_factory: async_sessionmaker, policy: RetentionPolicy, *, day: str | None = None
) -> str:
    day = day or _yesterday_kst()
    async with session_factory() as session:
        trades = list(
            (await session.execute(select(TradeRow))).scalars().all()
        )
        rows = [t for t in trades if _day_of(t.closed_at, t.ts) == day]

        # clear existing summaries for the day
        for model in (DailySymbolPnlRow, DailyStrategyPnlRow, DailyEntryModePnlRow,
                      DailyEventSummaryRow, DailyManualInterventionSummaryRow):
            await session.execute(delete(model).where(model.day == day))

        def _bucket(rows, keyfn, default_mode="PAPER"):
            agg: dict = {}
            for t in rows:
                mode = t.mode or default_mode
                key = (mode, keyfn(t))
                a = agg.setdefault(key, {"n": 0, "w": 0, "l": 0,
                                         "realized": Decimal(0), "fees": Decimal(0),
                                         "net": Decimal(0)})
                net = _D(t.net_pnl if t.net_pnl is not None else t.realized_pnl)
                a["n"] += 1
                a["w"] += 1 if net > 0 else 0
                a["l"] += 1 if net < 0 else 0
                a["realized"] += _D(t.realized_pnl)
                a["fees"] += _D(t.fees)
                a["net"] += net
            return agg

        for (mode, symbol), a in _bucket(rows, lambda t: t.symbol).items():
            session.add(DailySymbolPnlRow(
                day=day, mode=mode, symbol=symbol, trade_count=a["n"],
                win_count=a["w"], loss_count=a["l"], realized=str(a["realized"]),
                fees=str(a["fees"]), net=str(a["net"])))
        for (mode, strat), a in _bucket(rows, lambda t: t.strategy_id or "unknown").items():
            session.add(DailyStrategyPnlRow(
                day=day, mode=mode, strategy_id=strat, trade_count=a["n"],
                win_count=a["w"], loss_count=a["l"], realized=str(a["realized"]),
                fees=str(a["fees"]), net=str(a["net"])))
        for (mode, em), a in _bucket(rows, lambda t: t.entry_mode or "unknown").items():
            session.add(DailyEntryModePnlRow(
                day=day, mode=mode, entry_mode=em, trade_count=a["n"],
                win_count=a["w"], loss_count=a["l"], realized=str(a["realized"]),
                fees=str(a["fees"]), net=str(a["net"])))

        # daily_pnl upsert (aggregate across modes)
        realized = sum((_D(t.realized_pnl) for t in rows), Decimal(0))
        fees = sum((_D(t.fees) for t in rows), Decimal(0))
        net = sum((_D(t.net_pnl if t.net_pnl is not None else t.realized_pnl) for t in rows),
                  Decimal(0))
        existing = (await session.execute(
            select(DailyPnlRow).where(DailyPnlRow.day == day)
        )).scalar_one_or_none()
        if existing is None:
            session.add(DailyPnlRow(day=day, realized=str(realized), unrealized="0",
                                    fees=str(fees), net=str(net)))
        else:
            existing.realized, existing.fees, existing.net = (
                str(realized), str(fees), str(net))

        # event summary by severity
        events = list((await session.execute(select(BotEventRow))).scalars().all())
        ev = [e for e in events if _day_of(None, e.ts) == day]
        by_sev = {"INFO": 0, "WARNING": 0, "ERROR": 0, "CRITICAL": 0}
        emergency = tpsl_failed = 0
        for e in ev:
            by_sev[(e.severity or "INFO").upper()] = by_sev.get(
                (e.severity or "INFO").upper(), 0) + 1
            if e.type.startswith("EMERGENCY"):
                emergency += 1
            if e.type == "EMERGENCY_TPSL_FAILED" or e.type == "TPSL_FAILED":
                tpsl_failed += 1
        for mode in {t.mode or "PAPER" for t in rows} or {"PAPER"}:
            session.add(DailyEventSummaryRow(
                day=day, mode=mode, info_count=by_sev["INFO"],
                warning_count=by_sev["WARNING"], error_count=by_sev["ERROR"],
                critical_count=by_sev["CRITICAL"], emergency_count=emergency,
                tpsl_failed_count=tpsl_failed))

        # manual intervention summary
        manuals = list(
            (await session.execute(select(ManualInterventionLogRow))).scalars().all())
        mrows = [m for m in manuals if _day_of(None, m.ts) == day]
        by_kind: dict[str, int] = {}
        for m in mrows:
            by_kind[m.kind] = by_kind.get(m.kind, 0) + 1
        session.add(DailyManualInterventionSummaryRow(
            day=day, mode="PAPER", count=len(mrows), by_kind=by_kind))

        await _touch_status(session, last_summary_at=_utcnow())
        await session.commit()
    return day


# --------------------------------------------------------------------------- #
# archive (00:20 KST)
# --------------------------------------------------------------------------- #
_ARCHIVE_MAP = [
    ("orders", OrderRow, OrdersArchiveRow),
    ("fills", FillRow, FillsArchiveRow),
    ("trades", TradeRow, TradesArchiveRow),
    ("bot_events", BotEventRow, BotEventsArchiveRow),
    ("reconciliation_logs", ReconciliationLogRow, ReconciliationLogsArchiveRow),
]


async def archive_job(
    session_factory: async_sessionmaker, policy: RetentionPolicy, *,
    now: datetime | None = None,
) -> int:
    now = now or _utcnow()
    moved = 0
    async with session_factory() as session:
        for table, src, arch in _ARCHIVE_MAP:
            policy_table = "bot_events_info" if table == "bot_events" else table
            after = policy.archive_after_days(policy_table)
            if after is None:
                continue
            cutoff = now - timedelta(days=after)
            rows = list((await session.execute(
                select(src).where(src.ts < cutoff))).scalars().all())
            for row in rows:
                session.add(arch(payload=_serialize(row), source_id=row.id, ts=row.ts))
                moved += 1
                mode = getattr(row, "mode", None)
                event_type = getattr(row, "type", None)
                # archived; delete original unless delete-protected
                if not policy.is_row_delete_protected(
                    table=table, mode=mode, event_type=event_type
                ):
                    await session.delete(row)
        await _touch_status(session, last_archive_at=now)
        await session.commit()
    return moved


# --------------------------------------------------------------------------- #
# retention cleanup (00:40 KST)
# --------------------------------------------------------------------------- #
async def retention_cleanup(
    session_factory: async_sessionmaker, policy: RetentionPolicy, *,
    now: datetime | None = None,
) -> int:
    """Delete rows past keep_days. Skips delete-protected rows and PAPER detail
    tables whose daily summary for the cutoff day does not yet exist (§25.4/§25.11)."""
    now = now or _utcnow()
    deleted = 0
    async with session_factory() as session:
        summary_exists = (await session.execute(
            select(func.count()).select_from(DailyPnlRow))).scalar_one() > 0

        targets = [
            ("orders", OrderRow), ("fills", FillRow), ("trades", TradeRow),
            ("reconciliation_logs", ReconciliationLogRow),
        ]
        for table, src in targets:
            policy_table = table
            keep = policy.keep_days(policy_table)
            if keep is None:
                continue
            cutoff = now - timedelta(days=keep)
            rows = list((await session.execute(
                select(src).where(src.ts < cutoff))).scalars().all())
            for row in rows:
                mode = getattr(row, "mode", None)
                # PAPER detail rows require summaries first
                if mode == "PAPER" and not summary_exists and table in (
                    "orders", "fills", "trades"
                ):
                    continue
                if policy.is_row_delete_protected(table=table, mode=mode):
                    continue
                await session.delete(row)
                deleted += 1

        # bot_events by severity
        ev_rows = list((await session.execute(select(BotEventRow))).scalars().all())
        for e in ev_rows:
            sev = (e.severity or "INFO").upper()
            policy_table = {
                "INFO": "bot_events_info", "WARNING": "bot_events_warning",
            }.get(sev, "bot_events_error")
            keep = policy.keep_days(policy_table)
            if keep is None:
                continue
            if e.ts >= now - timedelta(days=keep):
                continue
            if policy.is_protected_event(e.type):
                continue
            await session.delete(e)
            deleted += 1

        await _touch_status(session, last_cleanup_at=now)
        await session.commit()
    return deleted


# --------------------------------------------------------------------------- #
# database health check (hourly)
# --------------------------------------------------------------------------- #
async def database_health_check(session_factory: async_sessionmaker) -> bool:
    try:
        async with session_factory() as session:
            await session.execute(select(1))
            await _touch_status(session, last_health_check_at=_utcnow())
            await session.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("db health check failed: %s", exc)
        return False
