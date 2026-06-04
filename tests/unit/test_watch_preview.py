"""build_watch_entry: readiness/direction derivation for the dashboard watch list."""

from decimal import Decimal

from packages.core.enums import SignalDirection
from packages.core.models import Signal
from packages.signal import build_watch_entry
from tests.fakes.builders import indicator_snapshot as snap


def _long_signal(score="7"):
    return Signal(symbol="BTCUSDT", direction=SignalDirection.LONG,
                  strategy="trend_following", score=Decimal(score), reason="trend long")


def _entry(last_price, *, signal=None, box_high="100", box_low="95",
           ema20="101", ema50="100", margin="0.1"):
    return build_watch_entry(
        symbol="BTCUSDT",
        signal=signal,
        snapshot_1m=snap(timeframe="1", close=last_price, atr="1", rsi="55",
                         volume_ratio="1.5", atr_percent="2.0"),
        snapshot_15m=snap(timeframe="15", ema20=ema20, ema50=ema50),
        box_high=Decimal(box_high), box_low=Decimal(box_low),
        last_price=Decimal(last_price), breakout_margin_atr=Decimal(margin),
        now_ms=1_000,
    )


def test_long_far_below_box_is_watching():
    e = _entry("99", signal=_long_signal())
    assert e["direction"] == "LONG"
    assert e["readiness"] == "WATCHING"
    assert e["trend"] == "UP"  # ema20 > ema50
    assert e["distance_atr"] == "1"


def test_long_in_scout_zone():
    assert _entry("99.7", signal=_long_signal())["readiness"] == "SCOUT_ZONE"


def test_long_near_breakout():
    assert _entry("99.9", signal=_long_signal())["readiness"] == "NEAR"


def test_long_already_broken_out():
    e = _entry("100.2", signal=_long_signal())
    assert e["readiness"] == "BREAKOUT"
    # remaining distance is negative once price is beyond the box
    assert Decimal(e["distance_atr"]) < 0


def test_short_uses_box_low():
    sig = Signal(symbol="BTCUSDT", direction=SignalDirection.SHORT,
                 strategy="trend_following", score=Decimal("6"), reason="trend short")
    e = _entry("95.05", signal=sig, ema20="99", ema50="100")
    assert e["direction"] == "SHORT"
    assert e["readiness"] == "NEAR"  # 0.05 ATR above box_low
    assert e["trend"] == "DOWN"


def test_no_signal_reports_none_but_keeps_indicators():
    e = _entry("99", signal=None)
    assert e["direction"] == "NONE"
    assert e["readiness"] == "NO_SIGNAL"
    assert e["signal_score"] is None
    assert e["distance_atr"] is None
    # indicators still surfaced so the user sees why nothing fired
    assert e["rsi"] == "55"
    assert e["atr_percent"] == "2.0"
    assert e["trend"] == "UP"
