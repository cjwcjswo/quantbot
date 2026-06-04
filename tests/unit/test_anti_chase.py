"""Tests for the Anti-Chase filter (impl doc §9)."""

from decimal import Decimal

from packages.entry import metrics_of
from packages.entry.anti_chase import AntiChase
from tests.fakes.builders import candle
from tests.fakes.builders import indicator_snapshot as snap


def _flat_1m(n=5, price="100"):
    return [
        candle(
            interval="1", open_time_ms=i * 60_000,
            o=price, h=str(Decimal(price) + 1), l=str(Decimal(price) - 1), c=price,
        )
        for i in range(n)
    ]


def _calm_long_snap():
    return snap(
        timeframe="1", close="100", ema20="100", atr="1", rsi="55", volume_ratio="1.0"
    )


def test_long_not_blocked_when_calm(config):
    ac = AntiChase(config)
    candles = _flat_1m()
    last = candle(interval="1", o="99.8", h="100.1", l="99.7", c="100.0")
    candles[-1] = last
    assert ac.block_long(_calm_long_snap(), candles, metrics_of(last)) is None


def test_long_blocked_overbought(config):
    ac = AntiChase(config)
    candles = _flat_1m()
    s = snap(timeframe="1", close="100", ema20="100", atr="1", rsi="73", volume_ratio="1.0")
    assert ac.block_long(s, candles, metrics_of(candles[-1])) == "RSI_OVERBOUGHT"


def test_long_blocked_far_above_ema(config):
    ac = AntiChase(config)
    candles = _flat_1m()
    s = snap(timeframe="1", close="100", ema20="90", atr="1", rsi="55", volume_ratio="1.0")
    assert ac.block_long(s, candles, metrics_of(candles[-1])) == "PRICE_FAR_ABOVE_EMA"


def test_long_blocked_single_candle_spike(config):
    ac = AntiChase(config)
    # Flats near 101 keep the 3-candle run-up small so the single-candle rule fires.
    candles = _flat_1m(price="101")
    spike = candle(interval="1", o="101.3", h="102.9", l="101.2", c="102.7")  # +1.4 body
    candles[-1] = spike
    s = snap(timeframe="1", close="102.7", ema20="102.4", atr="1", rsi="60", volume_ratio="1.0")
    assert ac.block_long(s, candles, metrics_of(spike)) == "SINGLE_CANDLE_SPIKE"


def test_long_blocked_weak_close(config):
    ac = AntiChase(config)
    candles = _flat_1m()
    # close in lower part of range => cpr < 0.75
    weak = candle(interval="1", o="100", h="100.5", l="99.5", c="99.7")
    candles[-1] = weak
    s = snap(timeframe="1", close="99.7", ema20="100", atr="1", rsi="55", volume_ratio="1.0")
    assert ac.block_long(s, candles, metrics_of(weak)) == "WEAK_CLOSE_IN_RANGE"


def test_short_blocked_oversold(config):
    ac = AntiChase(config)
    candles = _flat_1m()
    s = snap(timeframe="1", close="100", ema20="100", atr="1", rsi="27", volume_ratio="1.0")
    assert ac.block_short(s, candles, metrics_of(candles[-1])) == "RSI_OVERSOLD"


def test_disabled_never_blocks(config):
    config.entry.anti_chase.enabled = False
    ac = AntiChase(config)
    candles = _flat_1m()
    s = snap(timeframe="1", close="100", ema20="90", atr="1", rsi="90", volume_ratio="9.0")
    assert ac.block_long(s, candles, metrics_of(candles[-1])) is None
