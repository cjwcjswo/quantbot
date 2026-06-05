"""Tests for EntryTimingEngine (impl doc §10, §11)."""

from decimal import Decimal

from packages.core.enums import EntryMode, SignalDirection
from packages.entry import EntryTimingEngine
from packages.entry.entry_timing_engine import EntryContext
from tests.fakes.builders import candle
from tests.fakes.builders import indicator_snapshot as snap


def _ctx(
    *,
    candles_1m,
    box_high="100",
    box_low="98",
    s1_kwargs=None,
    direction=SignalDirection.LONG,
):
    s1_args = dict(
        timeframe="1", close=str(candles_1m[-1].close),
        ema20="100.5", atr="1", rsi="60", volume_ratio="2.0",
    )
    s1_args.update(s1_kwargs or {})
    s1 = snap(**s1_args)
    s5 = snap(timeframe="5", close="100", ema20="99", atr="1", atr_percent="1.5",
              rsi="60", volume_ratio="1.0")
    s15 = snap(timeframe="15", close="100", ema20="100", ema50="98", slope="0.2",
               atr="1", atr_percent="1.5", volume_ratio="1.0")
    return EntryContext(
        symbol="BTCUSDT",
        direction=direction,
        snapshot_1m=s1,
        snapshot_5m=s5,
        snapshot_15m=s15,
        candles_1m=candles_1m,
        box_high=Decimal(box_high),
        box_low=Decimal(box_low),
        signal_score=Decimal("7"),
    )


def _flat(n, price="100"):
    return [
        candle(interval="1", open_time_ms=i * 60_000, o=price, h=str(Decimal(price) + Decimal("0.2")),
               l=str(Decimal(price) - Decimal("0.2")), c=price)
        for i in range(n)
    ]


def test_healthy_breakout_returns_breakout_confirm(config):
    eng = EntryTimingEngine(config)
    candles = _flat(5, price="100")
    breakout = candle(interval="1", o="100.2", h="101.1", l="100.0", c="101.0")
    candles.append(breakout)
    decision = eng.evaluate(_ctx(candles_1m=candles, box_high="100"))
    assert decision is not None
    assert decision.entry_mode == EntryMode.BREAKOUT_CONFIRM
    assert decision.position_fraction == Decimal("0.35")
    assert decision.stop_atr == Decimal("1.0")


def test_exhaustion_breakout_then_retest(config):
    eng = EntryTimingEngine(config)
    candles = _flat(5, price="100")
    # exhaustion: same breakout candle but volume_ratio >= 4.0
    breakout = candle(interval="1", o="100.2", h="101.1", l="100.0", c="101.0")
    candles.append(breakout)
    ex = eng.evaluate(
        _ctx(candles_1m=candles, box_high="100", s1_kwargs={"volume_ratio": "5.0"})
    )
    assert ex is None  # no immediate entry
    assert eng.retests.get("BTCUSDT") is not None  # pending registered

    # retest candle: pulls back to the level (100) and holds, close > open
    retest = candle(interval="1", o="99.95", h="100.1", l="99.9", c="100.01")
    candles.append(retest)
    decision = eng.evaluate(_ctx(candles_1m=candles, box_high="100"))
    assert decision is not None
    assert decision.entry_mode == EntryMode.RETEST_CONFIRM
    assert decision.position_fraction == Decimal("0.45")


def test_no_breakout_no_pending_no_entry(config):
    eng = EntryTimingEngine(config)
    candles = _flat(5, price="99")  # well below box_high 100
    decision = eng.evaluate(_ctx(candles_1m=candles, box_high="100"))
    assert decision is None


def test_invalid_last_candle_returns_none(config):
    eng = EntryTimingEngine(config)
    candles = _flat(5)
    bad = candle(interval="1", o="100", h="100", l="100", c="100")  # range 0
    candles.append(bad)
    assert eng.evaluate(_ctx(candles_1m=candles)) is None


def test_retest_pending_expires(config):
    config.entry.retest_confirm.max_wait_candles = 2
    eng = EntryTimingEngine(config)
    eng.retests.register("BTCUSDT", SignalDirection.LONG, Decimal("100"))
    below = candle(interval="1", o="99", h="99.3", l="98.8", c="99")
    # 3 bars below the level => exceeds max_wait (and 2 consecutive wrong-side)
    for _ in range(3):
        eng.retests.on_new_bar("BTCUSDT", below)
    assert eng.retests.get("BTCUSDT") is None


def _scout_candles():
    """120 1m candles: wide early (high TR) then narrow recent (compression),
    with rising lows in the last few candles and a strong-close final candle
    coiling just under the box."""
    candles = []
    # 100 wide candles (range 2) at ~100
    for i in range(100):
        candles.append(
            candle(interval="1", open_time_ms=i * 60_000,
                   o="100", h="101", l="99", c="100")
        )
    # 16 narrow candles (range 0.2)
    for i in range(100, 116):
        candles.append(
            candle(interval="1", open_time_ms=i * 60_000,
                   o="100", h="100.1", l="99.9", c="100")
        )
    # 4 candles with rising lows, coiling up under the box (high close)
    lows = ["100.0", "100.05", "100.1", "100.2"]
    closes = ["100.15", "100.2", "100.3", "100.4"]
    for j, (lo, cl) in enumerate(zip(lows, closes)):
        opn = str(Decimal(cl) - Decimal("0.1"))
        hi = str(Decimal(cl) + Decimal("0.05"))
        candles.append(
            candle(interval="1", open_time_ms=(116 + j) * 60_000,
                   o=opn, h=hi, l=lo, c=cl)
        )
    return candles


def test_scout_entry(config):
    eng = EntryTimingEngine(config)
    candles = _scout_candles()
    ctx = _ctx(
        candles_1m=candles, box_high="100.5",
        s1_kwargs={"ema20": "100", "rsi": "55", "volume_ratio": "2.0", "atr": "1"},
    )
    decision = eng.evaluate(ctx)
    assert decision is not None
    assert decision.entry_mode == EntryMode.PRE_BREAKOUT_SCOUT
    assert decision.position_fraction == Decimal("0.35")
    assert decision.stop_atr == Decimal("0.7")
    assert decision.score >= Decimal("8")
