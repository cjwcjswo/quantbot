"""Watch preview: a read-only, non-committal entry summary per watched symbol.

The dashboard uses this so a user can see what the bot is watching, which way it
leans (LONG/SHORT) and how close each symbol is to a real entry trigger — without
the bot placing any order. It NEVER mutates entry-timing state: the
EntryTimingEngine alone decides real entries (arch §6.18). The readiness label is
derived from the same breakout/scout thresholds the engine uses, purely for
display.
"""

from __future__ import annotations

import time
from decimal import Decimal

from packages.core.enums import SignalDirection
from packages.core.models import IndicatorSnapshot, Signal

# Display defaults, overridden by EntryTimingEngine scout config when provided.
_NEAR_ATR = Decimal("0.20")
_SCOUT_ATR = Decimal("0.35")


def _trend(s15: IndicatorSnapshot) -> str:
    if s15.ema20 is None or s15.ema50 is None:
        return "FLAT"
    if s15.ema20 > s15.ema50:
        return "UP"
    if s15.ema20 < s15.ema50:
        return "DOWN"
    return "FLAT"


def _str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _readiness(
    *,
    is_long: bool,
    last_price: Decimal,
    boundary: Decimal,
    atr1: Decimal | None,
    margin_atr: Decimal,
    near_atr: Decimal,
    scout_atr: Decimal,
) -> tuple[str, Decimal | None]:
    """Return (readiness, remaining_distance_in_atr).

    ``remaining`` is how far price must still move to reach the breakout boundary
    (>0 = not there yet). Negative once price is already beyond it.
    """
    remaining = (boundary - last_price) if is_long else (last_price - boundary)
    if atr1 is None or atr1 <= 0:
        readiness = "BREAKOUT" if remaining < 0 else "WATCHING"
        return readiness, None
    dist_atr = remaining / atr1
    if dist_atr < -margin_atr:
        readiness = "BREAKOUT"
    elif dist_atr <= near_atr:
        readiness = "NEAR"
    elif dist_atr <= scout_atr:
        readiness = "SCOUT_ZONE"
    else:
        readiness = "WATCHING"
    return readiness, dist_atr


def build_watch_entry(
    *,
    symbol: str,
    signal: Signal | None,
    snapshot_1m: IndicatorSnapshot,
    snapshot_15m: IndicatorSnapshot,
    box_high: Decimal,
    box_low: Decimal,
    last_price: Decimal,
    breakout_margin_atr: Decimal,
    near_zone_atr: Decimal | None = None,
    scout_zone_atr: Decimal | None = None,
    now_ms: int | None = None,
) -> dict:
    """Build one JSON-serializable watch-list entry for ``symbol``.

    With no firing signal the entry still reports the 15m trend lean and the live
    indicators (direction ``NONE``), so the user can see *why* nothing fired yet.
    """
    s1, s15 = snapshot_1m, snapshot_15m
    atr1 = s1.atr14

    if signal is not None and signal.direction in (
        SignalDirection.LONG,
        SignalDirection.SHORT,
    ):
        is_long = signal.direction == SignalDirection.LONG
        boundary = box_high if is_long else box_low
        readiness, dist_atr = _readiness(
            is_long=is_long, last_price=last_price, boundary=boundary,
            atr1=atr1, margin_atr=breakout_margin_atr,
            near_atr=near_zone_atr or _NEAR_ATR,
            scout_atr=scout_zone_atr or _SCOUT_ATR,
        )
        remaining = (boundary - last_price) if is_long else (last_price - boundary)
        dist_pct = (
            remaining / last_price * Decimal(100) if last_price > 0 else None
        )
        direction = signal.direction.value
        score = _str(signal.score)
        reason = signal.reason or None
        strategy = signal.strategy
    else:
        readiness, dist_atr, dist_pct = "NO_SIGNAL", None, None
        direction, score, reason, strategy = "NONE", None, None, None

    return {
        "symbol": symbol,
        "strategy": strategy,
        "direction": direction,
        "signal_score": score,
        "signal_reason": reason,
        "readiness": readiness,
        "trend": _trend(s15),
        "last_price": _str(last_price),
        "box_high": _str(box_high),
        "box_low": _str(box_low),
        "distance_to_breakout_pct": _str(dist_pct),
        "distance_atr": _str(dist_atr),
        "atr_percent": _str(s1.atr_percent),
        "rsi": _str(s1.rsi14),
        "volume_ratio": _str(s1.volume_ratio),
        "updated_ms": now_ms if now_ms is not None else int(time.time() * 1000),
    }
