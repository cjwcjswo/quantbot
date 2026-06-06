"""Domain enums.

All values are intentionally string-valued so they can be serialized to Redis /
PostgreSQL / JSON without translation.
"""

from __future__ import annotations

from enum import StrEnum


class BotState(StrEnum):
    """Bot Engine lifecycle / execution state (impl doc §3.1).

    Program start only auto-advances BOOTING -> STANDBY. STANDBY -> RUNNING
    requires an explicit user START command.
    """

    BOOTING = "BOOTING"
    STANDBY = "STANDBY"
    START_REQUESTED = "START_REQUESTED"
    SYNCING = "SYNCING"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    RISK_LOCKED = "RISK_LOCKED"
    RECONCILING = "RECONCILING"
    ORDER_LOCKED = "ORDER_LOCKED"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"


class BotMode(StrEnum):
    """Execution mode. PAPER uses real market data + virtual fills; LIVE is real."""

    PAPER = "PAPER"
    LIVE = "LIVE"


class Side(StrEnum):
    """Order / trade side (Bybit: Buy / Sell)."""

    BUY = "Buy"
    SELL = "Sell"


class PositionSide(StrEnum):
    """Direction of a held position."""

    LONG = "LONG"
    SHORT = "SHORT"


class OrderType(StrEnum):
    """Internal order type.

    AGGRESSIVE_LIMIT is a marketable limit (IOC) used for breakout confirm in LIVE.
    MARKET is only allowed for reduce-only exits in LIVE (impl doc §2.2, §12).
    """

    LIMIT = "LIMIT"
    AGGRESSIVE_LIMIT = "AGGRESSIVE_LIMIT"
    MARKET = "MARKET"


class OrderStatus(StrEnum):
    """Lifecycle of an order."""

    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class TimeInForce(StrEnum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"
    POST_ONLY = "PostOnly"


class TriggerBy(StrEnum):
    """Trigger price reference for TP/SL (Bybit)."""

    LAST_PRICE = "LastPrice"
    MARK_PRICE = "MarkPrice"
    INDEX_PRICE = "IndexPrice"


class PositionStatus(StrEnum):
    """Internal position lifecycle.

    A LIVE position only becomes ACTIVE once entry fill + Bybit position +
    TP/SL set + TP/SL verify all succeed (impl doc §14.1).
    """

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class PositionSource(StrEnum):
    """Where a position originated.

    EXTERNAL positions (created via Bybit app / outside the bot) are adopted for
    display but NOT auto-managed (impl doc §4.3 manage_adopted_positions=false).
    """

    BOT = "BOT"
    EXTERNAL = "EXTERNAL"


class ScoutState(StrEnum):
    """Runtime state for PRE_BREAKOUT_SCOUT position management."""

    NONE = "NONE"
    SCOUT_PENDING = "SCOUT_PENDING"
    SCOUT_WARNING = "SCOUT_WARNING"
    SCOUT_CONFIRMED = "SCOUT_CONFIRMED"
    ACTIVE_TREND = "ACTIVE_TREND"


class EntryMode(StrEnum):
    """Entry timing mode (impl doc §11)."""

    PRE_BREAKOUT_SCOUT = "PRE_BREAKOUT_SCOUT"
    BREAKOUT_CONFIRM = "BREAKOUT_CONFIRM"
    RETEST_CONFIRM = "RETEST_CONFIRM"


class SignalDirection(StrEnum):
    """Strategy candidate direction."""

    LONG = "LONG"
    SHORT = "SHORT"
    EXIT = "EXIT"


class ExitReason(StrEnum):
    """Reason a position (or partial) was closed."""

    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    PARTIAL_TAKE_PROFIT = "PARTIAL_TAKE_PROFIT"
    TRAILING_STOP = "TRAILING_STOP"
    STAGNATION = "STAGNATION"
    SCENARIO_INVALID = "SCENARIO_INVALID"
    SCOUT_DEFENSIVE_REDUCE = "SCOUT_DEFENSIVE_REDUCE"
    SCOUT_CATASTROPHIC_REDUCE = "SCOUT_CATASTROPHIC_REDUCE"
    MAX_HOLDING_TIME = "MAX_HOLDING_TIME"
    MANUAL_CLOSE = "MANUAL_CLOSE"
    EMERGENCY_CLOSE = "EMERGENCY_CLOSE"
    FUNDING_GUARD = "FUNDING_GUARD"
    PARTIAL_FILL_TOO_SMALL = "PARTIAL_FILL_TOO_SMALL"
    TPSL_FAILED = "TPSL_FAILED"
