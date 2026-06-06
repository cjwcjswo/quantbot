"""SQLAlchemy ORM models for the persisted tables (arch doc §7).

Money fields are stored as TEXT (str(Decimal)) to preserve exact precision across
PostgreSQL and SQLite without float rounding. Structured payloads use JSON.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class _Row(Base):
    __abstract__ = True
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class BotEventRow(_Row):
    __tablename__ = "bot_events"
    type: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    message: Mapped[str] = mapped_column(String(512), default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    severity: Mapped[str] = mapped_column(String(16), default="INFO")


class SignalRow(_Row):
    __tablename__ = "signals"
    symbol: Mapped[str] = mapped_column(String(32))
    direction: Mapped[str] = mapped_column(String(8))
    strategy: Mapped[str] = mapped_column(String(64))
    score: Mapped[str] = mapped_column(String(32), default="0")
    reason: Mapped[str] = mapped_column(String(512), default="")
    entry_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)


class OrderRow(_Row):
    __tablename__ = "orders"
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(8))
    order_type: Mapped[str] = mapped_column(String(24))
    qty: Mapped[str] = mapped_column(String(32))
    price: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(24))
    client_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reduce_only: Mapped[bool] = mapped_column(Boolean, default=False)
    entry_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    mode: Mapped[str | None] = mapped_column(String(8), nullable=True)
    filled_qty: Mapped[str | None] = mapped_column(String(32), nullable=True)
    avg_fill_price: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class FillRow(_Row):
    __tablename__ = "fills"
    symbol: Mapped[str] = mapped_column(String(32))
    order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    side: Mapped[str] = mapped_column(String(8))
    price: Mapped[str] = mapped_column(String(32))
    qty: Mapped[str] = mapped_column(String(32))
    fee: Mapped[str] = mapped_column(String(32), default="0")
    realized_pnl: Mapped[str] = mapped_column(String(32), default="0")
    mode: Mapped[str | None] = mapped_column(String(8), nullable=True)
    slippage: Mapped[str | None] = mapped_column(String(32), nullable=True)


class PositionRow(_Row):
    __tablename__ = "positions"
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16), default="BOT")
    qty: Mapped[str] = mapped_column(String(32))
    avg_entry_price: Mapped[str] = mapped_column(String(32))
    manual_added_qty: Mapped[str] = mapped_column(String(32), default="0")
    stop_loss_price: Mapped[str | None] = mapped_column(String(32), nullable=True)
    take_profit_price: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entry_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    realized_pnl: Mapped[str] = mapped_column(String(32), default="0")
    exit_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    mode: Mapped[str | None] = mapped_column(String(8), nullable=True)
    leverage: Mapped[str | None] = mapped_column(String(16), nullable=True)
    mark_price: Mapped[str | None] = mapped_column(String(32), nullable=True)
    unrealized_pnl: Mapped[str | None] = mapped_column(String(32), nullable=True)
    strategy_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    protection_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TradeRow(_Row):
    __tablename__ = "trades"
    trade_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(8))
    qty: Mapped[str] = mapped_column(String(32))
    entry_price: Mapped[str] = mapped_column(String(32))
    exit_price: Mapped[str | None] = mapped_column(String(32), nullable=True)
    realized_pnl: Mapped[str] = mapped_column(String(32), default="0")
    exit_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    strategy_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mode: Mapped[str | None] = mapped_column(String(8), nullable=True)
    leverage: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fees: Mapped[str] = mapped_column(String(32), default="0")
    funding_fees: Mapped[str] = mapped_column(String(32), default="0")
    gross_pnl: Mapped[str | None] = mapped_column(String(32), nullable=True)
    net_pnl: Mapped[str | None] = mapped_column(String(32), nullable=True)
    r_multiple: Mapped[str | None] = mapped_column(String(16), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ReconciliationLogRow(_Row):
    __tablename__ = "reconciliation_logs"
    summary: Mapped[dict] = mapped_column(JSON, default=dict)


class ManualInterventionLogRow(_Row):
    __tablename__ = "manual_intervention_logs"
    symbol: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(48))
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class PositionProtectionLogRow(_Row):
    __tablename__ = "position_protection_logs"
    symbol: Mapped[str] = mapped_column(String(32))
    event: Mapped[str] = mapped_column(String(48))
    take_profit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stop_loss: Mapped[str | None] = mapped_column(String(32), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)


class CommandLogRow(_Row):
    __tablename__ = "command_logs"
    command_id: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[str] = mapped_column(String(32), default="received")


class DailyPnlRow(_Row):
    __tablename__ = "daily_pnl"
    day: Mapped[str] = mapped_column(String(16))
    realized: Mapped[str] = mapped_column(String(32), default="0")
    unrealized: Mapped[str] = mapped_column(String(32), default="0")
    fees: Mapped[str] = mapped_column(String(32), default="0")
    net: Mapped[str] = mapped_column(String(32), default="0")


class DailyAccountEquityRow(_Row):
    __tablename__ = "daily_account_equity"
    day: Mapped[str] = mapped_column(String(16), index=True)
    mode: Mapped[str] = mapped_column(String(8), default="PAPER", index=True)
    start_equity: Mapped[str] = mapped_column(String(32))
    current_equity: Mapped[str] = mapped_column(String(32))
    peak_equity: Mapped[str] = mapped_column(String(32))
    wallet_balance: Mapped[str | None] = mapped_column(String(32), nullable=True)
    unrealized_pnl: Mapped[str] = mapped_column(String(32), default="0")
    realized_pnl: Mapped[str] = mapped_column(String(32), default="0")
    fees: Mapped[str] = mapped_column(String(32), default="0")
    funding_fees: Mapped[str] = mapped_column(String(32), default="0")
    net_pnl: Mapped[str] = mapped_column(String(32), default="0")
    net_pnl_percent: Mapped[str] = mapped_column(String(32), default="0")
    max_drawdown_percent: Mapped[str] = mapped_column(String(32), default="0")
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class StrategyConfigRow(_Row):
    __tablename__ = "strategy_configs"
    name: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    mode: Mapped[str | None] = mapped_column(String(8), nullable=True)


class PaperAccountSnapshotRow(_Row):
    __tablename__ = "paper_account_snapshots"
    equity: Mapped[str] = mapped_column(String(32))
    balance: Mapped[str] = mapped_column(String(32))
    unrealized_pnl: Mapped[str] = mapped_column(String(32), default="0")


# --- §25 operational: archive tables (source columns + archived_at) ---


class _Archive(Base):
    __abstract__ = True
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    archived_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class OrdersArchiveRow(_Archive):
    __tablename__ = "orders_archive"


class FillsArchiveRow(_Archive):
    __tablename__ = "fills_archive"


class TradesArchiveRow(_Archive):
    __tablename__ = "trades_archive"


class BotEventsArchiveRow(_Archive):
    __tablename__ = "bot_events_archive"


class ReconciliationLogsArchiveRow(_Archive):
    __tablename__ = "reconciliation_logs_archive"


# --- §25 operational: daily summary tables ---


class DailySymbolPnlRow(_Row):
    __tablename__ = "daily_symbol_pnl"
    day: Mapped[str] = mapped_column(String(16), index=True)
    mode: Mapped[str] = mapped_column(String(8), default="PAPER")
    symbol: Mapped[str] = mapped_column(String(32))
    trade_count: Mapped[int] = mapped_column(Integer, default=0)
    win_count: Mapped[int] = mapped_column(Integer, default=0)
    loss_count: Mapped[int] = mapped_column(Integer, default=0)
    realized: Mapped[str] = mapped_column(String(32), default="0")
    fees: Mapped[str] = mapped_column(String(32), default="0")
    net: Mapped[str] = mapped_column(String(32), default="0")


class DailyStrategyPnlRow(_Row):
    __tablename__ = "daily_strategy_pnl"
    day: Mapped[str] = mapped_column(String(16), index=True)
    mode: Mapped[str] = mapped_column(String(8), default="PAPER")
    strategy_id: Mapped[str] = mapped_column(String(64))
    trade_count: Mapped[int] = mapped_column(Integer, default=0)
    win_count: Mapped[int] = mapped_column(Integer, default=0)
    loss_count: Mapped[int] = mapped_column(Integer, default=0)
    realized: Mapped[str] = mapped_column(String(32), default="0")
    fees: Mapped[str] = mapped_column(String(32), default="0")
    net: Mapped[str] = mapped_column(String(32), default="0")


class DailyEntryModePnlRow(_Row):
    __tablename__ = "daily_entry_mode_pnl"
    day: Mapped[str] = mapped_column(String(16), index=True)
    mode: Mapped[str] = mapped_column(String(8), default="PAPER")
    entry_mode: Mapped[str] = mapped_column(String(32))
    trade_count: Mapped[int] = mapped_column(Integer, default=0)
    win_count: Mapped[int] = mapped_column(Integer, default=0)
    loss_count: Mapped[int] = mapped_column(Integer, default=0)
    realized: Mapped[str] = mapped_column(String(32), default="0")
    fees: Mapped[str] = mapped_column(String(32), default="0")
    net: Mapped[str] = mapped_column(String(32), default="0")


class DailyEventSummaryRow(_Row):
    __tablename__ = "daily_event_summary"
    day: Mapped[str] = mapped_column(String(16), index=True)
    mode: Mapped[str] = mapped_column(String(8), default="PAPER")
    info_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    critical_count: Mapped[int] = mapped_column(Integer, default=0)
    emergency_count: Mapped[int] = mapped_column(Integer, default=0)
    tpsl_failed_count: Mapped[int] = mapped_column(Integer, default=0)


class DailyManualInterventionSummaryRow(_Row):
    __tablename__ = "daily_manual_intervention_summary"
    day: Mapped[str] = mapped_column(String(16), index=True)
    mode: Mapped[str] = mapped_column(String(8), default="PAPER")
    count: Mapped[int] = mapped_column(Integer, default=0)
    by_kind: Mapped[dict] = mapped_column(JSON, default=dict)


class RetentionStatusRow(_Row):
    __tablename__ = "retention_status"
    last_summary_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_archive_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_cleanup_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_health_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
