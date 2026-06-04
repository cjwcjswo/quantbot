"""Tests for indicator math (impl doc §8)."""

from decimal import Decimal

from packages.indicators import (
    IndicatorEngine,
    atr,
    ema_series,
    rsi,
    swing_high,
    swing_low,
    volume_ratio,
)
from tests.fakes.builders import series_from_closes


def test_ema_of_constant_is_constant():
    values = [Decimal("100")] * 30
    series = ema_series(values, 20)
    assert series[-1] == Decimal("100")


def test_ema_insufficient_data():
    assert ema_series([Decimal("1")] * 5, 20) is None


def test_rsi_all_up_is_100():
    closes = [Decimal(str(x)) for x in range(1, 30)]
    assert rsi(closes, 14) == Decimal("100")


def test_rsi_all_down_is_0():
    closes = [Decimal(str(x)) for x in range(30, 1, -1)]
    assert rsi(closes, 14) == Decimal("0")


def test_atr_constant_range():
    # Every candle has high-low = 2 and flat closes => TR = 2 => ATR = 2.
    candles = series_from_closes(["100"] * 30, spread="1")  # high/low = close +/- 1
    assert atr(candles, 14) == Decimal("2")


def test_volume_ratio_doubles():
    candles = series_from_closes(["100"] * 21, volume="1000")
    # bump the last candle's volume to 2000 => ratio 2.0
    last = candles[-1].model_copy(update={"volume": Decimal("2000")})
    candles[-1] = last
    assert volume_ratio(candles, 20) == Decimal("2")


def test_swing_high_low():
    candles = series_from_closes(
        ["100", "105", "98", "110", "95"], spread="0"
    )
    assert swing_high(candles, 5) == Decimal("110")
    assert swing_low(candles, 5) == Decimal("95")


def test_snapshot_valid_for_uptrend():
    closes = [Decimal("100") + Decimal("0.5") * i for i in range(60)]
    candles = series_from_closes(closes)
    engine = IndicatorEngine()
    snap = engine.snapshot("BTCUSDT", "15", candles)
    assert snap.valid
    assert snap.ema20 is not None and snap.ema50 is not None
    assert snap.ema20 > snap.ema50  # rising trend
    assert snap.ema20_slope_atr is not None and snap.ema20_slope_atr > 0
    assert snap.atr_percent is not None


def test_snapshot_invalid_with_too_few_candles():
    candles = series_from_closes(["100", "101", "102"])
    snap = IndicatorEngine().snapshot("BTCUSDT", "15", candles)
    assert not snap.valid
