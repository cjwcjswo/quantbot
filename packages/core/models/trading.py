"""Internal trading models: indicators, signals, orders, fills, positions."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from packages.core.enums import (
    EntryMode,
    ExitReason,
    OrderStatus,
    OrderType,
    PositionSide,
    PositionSource,
    PositionStatus,
    ScoutState,
    Side,
    SignalDirection,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class _Mut(BaseModel):
    model_config = ConfigDict(frozen=False, validate_assignment=True)


class IndicatorSnapshot(_Frozen):
    """Per-symbol indicator values for one evaluation (impl doc §6.14, §8).

    ``valid`` is False if any required indicator was NaN/unavailable, in which
    case entry is blocked (impl doc §15: "ATR/RSI/EMA 중 하나라도 NaN -> 진입 금지").
    """

    symbol: str
    timeframe: str
    close: Decimal
    ema20: Decimal | None = None
    ema50: Decimal | None = None
    ema20_slope_atr: Decimal | None = None  # slope over last 3 candles, in ATR units
    rsi14: Decimal | None = None
    atr14: Decimal | None = None
    atr_percent: Decimal | None = None
    volume_ratio: Decimal | None = None
    swing_high: Decimal | None = None
    swing_low: Decimal | None = None
    valid: bool = True
    ts_ms: int = 0


class Signal(_Frozen):
    """A standardized strategy signal (impl doc §6.17 SignalEngine output)."""

    symbol: str
    direction: SignalDirection
    strategy: str
    score: Decimal = Decimal("0")
    reason: str = ""
    created_at: datetime = Field(default_factory=_now)


class Fill(_Mut):
    """A single execution against an order."""

    symbol: str
    order_id: str
    side: Side
    price: Decimal
    qty: Decimal
    fee: Decimal = Decimal("0")
    is_maker: bool = False
    ts: datetime = Field(default_factory=_now)


class Order(_Mut):
    """Internal order record tracked by OrderManager."""

    symbol: str
    side: Side
    order_type: OrderType
    qty: Decimal
    price: Decimal | None = None
    client_order_id: str | None = None
    order_id: str | None = None
    status: OrderStatus = OrderStatus.NEW
    filled_qty: Decimal = Decimal("0")
    avg_fill_price: Decimal | None = None
    reduce_only: bool = False
    entry_mode: EntryMode | None = None
    source: PositionSource = PositionSource.BOT
    created_at: datetime = Field(default_factory=_now)


class Position(_Mut):
    """Internal position state managed by PositionManager (impl doc §14, §6.21).

    For positions whose qty was manually increased on the Bybit app, the bot
    reflects the real Bybit qty into ``qty`` and records the delta in
    ``manual_added_qty`` (impl doc §4.4) — without treating it as a new signal.
    """

    symbol: str
    side: PositionSide
    status: PositionStatus = PositionStatus.PENDING
    source: PositionSource = PositionSource.BOT

    qty: Decimal
    avg_entry_price: Decimal
    manual_added_qty: Decimal = Decimal("0")
    leverage: Decimal = Decimal("1")

    stop_loss_price: Decimal | None = None
    take_profit_price: Decimal | None = None
    initial_risk_per_unit: Decimal | None = None  # |entry - stop|, the "R" unit
    liq_price: Decimal | None = None

    entry_mode: EntryMode | None = None
    signal_score: Decimal = Decimal("0")
    strategy_id: str = ""
    strategy_reason: str = ""

    # runtime tracking
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    fees_paid: Decimal = Decimal("0")
    highest_price: Decimal | None = None  # for long trailing
    lowest_price: Decimal | None = None  # for short trailing
    partial_tp_done: bool = False
    trailing_active: bool = False
    runner_mode_active: bool = False
    runner_mode_started_at: datetime | None = None
    runner_trend_strength: str | None = None
    runner_trailing_atr_multiplier: Decimal | None = None
    last_runner_trailing_update_at: datetime | None = None
    last_runner_trailing_stop: Decimal | None = None
    runner_exchange_sl_update_failures: int = 0
    bars_since_entry: int = 0
    last_evaluated_1m_open_time_ms: int | None = None
    breakout_level: Decimal | None = None
    scout_state: ScoutState = ScoutState.NONE
    scout_entry_box_high: Decimal | None = None
    scout_entry_box_low: Decimal | None = None
    scout_entry_box_mid: Decimal | None = None
    scout_entry_level: Decimal | None = None
    scout_entry_bar_index: int | None = None
    scout_warning_started_at_bar: int | None = None
    scout_warning_reason: str | None = None
    scout_defensive_reduction_count: int = 0
    scout_confirmed_at: datetime | None = None

    opened_at: datetime = Field(default_factory=_now)
    closed_at: datetime | None = None
    exit_reason: ExitReason | None = None

    @property
    def is_long(self) -> bool:
        return self.side == PositionSide.LONG

    @property
    def is_active(self) -> bool:
        return self.status == PositionStatus.ACTIVE

    @property
    def is_bot_managed(self) -> bool:
        """EXTERNAL positions are not auto-managed (impl doc §4.3)."""
        return self.source == PositionSource.BOT
