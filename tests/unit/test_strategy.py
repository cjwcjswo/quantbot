"""Tests for TrendFollowingStrategy + SignalEngine (impl doc §8)."""

from decimal import Decimal

from packages.core.enums import SignalDirection
from packages.signal import SignalEngine
from packages.strategy import StrategyContext, StrategyRegistry, TrendFollowingStrategy
from tests.fakes.builders import indicator_snapshot as snap


def _long_snaps():
    s15 = snap(
        timeframe="15", close="100", ema20="99", ema50="98",
        slope="0.2", atr="1", atr_percent="1.5",
    )
    s5 = snap(
        timeframe="5", close="100.5", ema20="100", ema50="99",
        rsi="60", atr="1", atr_percent="1.5", volume_ratio="1.0",
    )
    return {"15": s15, "5": s5}


def _short_snaps():
    # 15m close must sit below EMA20 by >= 0.10 ATR (impl doc §8 short).
    s15 = snap(
        timeframe="15", close="100", ema20="101", ema50="102",
        slope="-0.2", atr="1", atr_percent="1.5",
    )
    s5 = snap(
        timeframe="5", close="99", ema20="100", ema50="101",
        rsi="40", atr="1", atr_percent="1.5", volume_ratio="1.0",
    )
    return {"15": s15, "5": s5}


def test_long_candidate(config):
    strat = TrendFollowingStrategy(config)
    sig = strat.evaluate(StrategyContext("BTCUSDT", _long_snaps()))
    assert sig is not None
    assert sig.direction == SignalDirection.LONG
    assert sig.strategy == "trend_following"
    assert sig.score > 0


def test_short_candidate(config):
    strat = TrendFollowingStrategy(config)
    sig = strat.evaluate(StrategyContext("BTCUSDT", _short_snaps()))
    assert sig is not None
    assert sig.direction == SignalDirection.SHORT


def test_no_signal_when_gap_too_small(config):
    snaps = _long_snaps()
    # EMA20 == EMA50 => gap 0 < 0.10
    snaps["15"] = snap(
        timeframe="15", close="100", ema20="99", ema50="99",
        slope="0.2", atr="1", atr_percent="1.5",
    )
    strat = TrendFollowingStrategy(config)
    assert strat.evaluate(StrategyContext("BTCUSDT", snaps)) is None


def test_no_signal_when_rsi_out_of_band(config):
    snaps = _long_snaps()
    snaps["5"] = snap(
        timeframe="5", close="100.5", ema20="100", ema50="99",
        rsi="75", atr="1", atr_percent="1.5", volume_ratio="1.0",  # > 68
    )
    strat = TrendFollowingStrategy(config)
    assert strat.evaluate(StrategyContext("BTCUSDT", snaps)) is None


def test_no_signal_when_setup_volume_too_low(config):
    snaps = _long_snaps()
    snaps["5"] = snap(
        timeframe="5", close="100.5", ema20="100", ema50="99",
        rsi="60", atr="1", atr_percent="1.5", volume_ratio="0.5",
    )
    strat = TrendFollowingStrategy(config)
    assert strat.evaluate(StrategyContext("BTCUSDT", snaps)) is None


def test_no_signal_when_atr_out_of_band(config):
    snaps = _long_snaps()
    snaps["5"] = snap(
        timeframe="5", close="100.5", ema20="100", ema50="99",
        rsi="60", atr="1", atr_percent="0.1", volume_ratio="1.0",  # < 0.15
    )
    strat = TrendFollowingStrategy(config)
    assert strat.evaluate(StrategyContext("BTCUSDT", snaps)) is None


def test_invalid_snapshot_no_signal(config):
    snaps = _long_snaps()
    snaps["5"] = snap(timeframe="5", close="100", valid=False)
    strat = TrendFollowingStrategy(config)
    assert strat.evaluate(StrategyContext("BTCUSDT", snaps)) is None


def test_signal_engine_dedup(config):
    registry = StrategyRegistry()
    registry.register(TrendFollowingStrategy(config))
    engine = SignalEngine(registry)
    sigs = engine.generate("BTCUSDT", _long_snaps())
    assert len(sigs) == 1
    assert sigs[0].direction == SignalDirection.LONG
    assert registry.required_timeframes() == {"5", "15"}
