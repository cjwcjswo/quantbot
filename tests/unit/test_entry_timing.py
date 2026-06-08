"""Tests for EntryTimingEngine (impl doc §10, §11)."""

from decimal import Decimal

from packages.core.enums import EntryMode, SignalDirection
from packages.entry import EntryTimingEngine
from packages.entry.entry_timing_engine import (
    EntryContext,
    resolve_retest_stop_atr,
    resolve_scout_stop_atr,
)
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
    breakout = candle(
        interval="1",
        open_time_ms=5 * 60_000,
        o="100.2",
        h="101.1",
        l="100.0",
        c="101.0",
    )
    candles.append(breakout)
    pending = eng.evaluate(_ctx(candles_1m=candles, box_high="100"))
    assert pending is None
    assert eng.last_no_entry_reason["reason_code"] == "BREAKOUT_HOLD_PENDING"

    candles.append(
        candle(
            interval="1",
            open_time_ms=6 * 60_000,
            o="100.5",
            h="101.4",
            l="100.45",
            c="101.2",
        )
    )
    decision = eng.evaluate(_ctx(candles_1m=candles, box_high="100"))
    assert decision is not None
    assert decision.entry_mode == EntryMode.BREAKOUT_CONFIRM
    assert decision.position_fraction == Decimal("0.75")
    assert decision.stop_atr == Decimal("1.0")


def test_breakout_volume_threshold_uses_entry_config(config):
    config.entry.breakout_confirm.require_next_candle_hold = False
    config.entry.breakout_confirm.volume_min_ratio = 1.2
    config.volume.min_breakout_volume_ratio = 9.0
    candles = _flat(5, price="100")
    candles.append(candle(interval="1", o="100.2", h="101.1", l="100.0", c="101.0"))

    decision = EntryTimingEngine(config).evaluate(
        _ctx(candles_1m=candles, box_high="100", s1_kwargs={"volume_ratio": "1.5"})
    )

    assert decision is not None
    assert decision.entry_mode == EntryMode.BREAKOUT_CONFIRM

    config.entry.breakout_confirm.volume_min_ratio = 2.0
    blocked = EntryTimingEngine(config)
    decision = blocked.evaluate(
        _ctx(candles_1m=candles, box_high="100", s1_kwargs={"volume_ratio": "1.5"})
    )

    assert decision is None
    assert blocked.last_no_entry_reason["reason_code"] == "BREAKOUT_NOT_HEALTHY"
    assert blocked.last_no_entry_reason["breakout_quality_reason"] == "VOLUME_TOO_LOW"


def test_breakout_hold_failure_registers_retest(config):
    eng = EntryTimingEngine(config)
    candles = _flat(5, price="100")
    candles.append(
        candle(
            interval="1",
            open_time_ms=5 * 60_000,
            o="100.2",
            h="101.1",
            l="100.0",
            c="101.0",
        )
    )

    assert eng.evaluate(_ctx(candles_1m=candles, box_high="100")) is None
    candles.append(
        candle(
            interval="1",
            open_time_ms=6 * 60_000,
            o="101.0",
            h="101.1",
            l="99.7",
            c="99.95",
        )
    )
    decision = eng.evaluate(_ctx(candles_1m=candles, box_high="100"))

    assert decision is None
    assert eng.last_no_entry_reason["reason_code"] == "BREAKOUT_HOLD_FAILED"
    assert eng.last_no_entry_reason["retest_pending_status"] == "REGISTERED"
    assert eng.retests.get("BTCUSDT") is not None


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
    decision = eng.evaluate(
        _ctx(
            candles_1m=candles,
            box_high="100",
            s1_kwargs={"atr_percent": "0.41"},
        )
    )
    assert decision is not None
    assert decision.entry_mode == EntryMode.RETEST_CONFIRM
    assert decision.position_fraction == Decimal("0.85")
    assert decision.stop_atr == Decimal("1.3")


def test_retest_adaptive_stop_atr_tiers(config):
    assert resolve_retest_stop_atr(
        Decimal("0.20"),
        Decimal(str(config.entry.retest_confirm.stop_atr)),
        config.volatility_adaptive_stop,
    ) == Decimal("1.0")
    assert resolve_retest_stop_atr(
        Decimal("0.41"),
        Decimal(str(config.entry.retest_confirm.stop_atr)),
        config.volatility_adaptive_stop,
    ) == Decimal("1.3")
    assert resolve_retest_stop_atr(
        Decimal("0.75"),
        Decimal(str(config.entry.retest_confirm.stop_atr)),
        config.volatility_adaptive_stop,
    ) == Decimal("1.5")


def test_scout_adaptive_stop_atr_tiers(config):
    assert resolve_scout_stop_atr(
        Decimal("0.20"),
        Decimal(str(config.entry.pre_breakout.stop_atr)),
        config.volatility_adaptive_stop,
    ) == Decimal("1.3")
    assert resolve_scout_stop_atr(
        Decimal("0.41"),
        Decimal(str(config.entry.pre_breakout.stop_atr)),
        config.volatility_adaptive_stop,
    ) == Decimal("1.0")
    assert resolve_scout_stop_atr(
        Decimal("0.75"),
        Decimal(str(config.entry.pre_breakout.stop_atr)),
        config.volatility_adaptive_stop,
    ) == Decimal("0.8")


def test_retest_short_structure_stop_from_recent_high(config):
    config.entry.enabled_modes.pre_breakout_scout = False
    eng = EntryTimingEngine(config)
    eng.retests.register("BTCUSDT", SignalDirection.SHORT, Decimal("98"))
    candles = _flat(4, price="98")
    candles.append(candle(interval="1", o="98.1", h="98.4", l="97.8", c="97.98"))

    decision = eng.evaluate(
        _ctx(
            candles_1m=candles,
            box_low="98",
            direction=SignalDirection.SHORT,
            s1_kwargs={"atr": "1", "atr_percent": "0.41", "rsi": "40"},
        )
    )

    assert decision is not None
    assert decision.entry_mode == EntryMode.RETEST_CONFIRM
    assert decision.stop_atr == Decimal("1.3")
    assert decision.structure_stop_price == Decimal("98.5")
    assert decision.stop_metadata["adaptive_stop_tier"] == "0.25-0.60"
    assert decision.stop_metadata["retest_swing_high"] == "98.4"


def test_retest_structure_unavailable_uses_atr_only(config):
    config.structure_stop.enabled = True
    eng = EntryTimingEngine(config)
    ctx = _ctx(candles_1m=_flat(3), s1_kwargs={"atr_percent": "0.41"})
    ctx = EntryContext(
        symbol=ctx.symbol,
        direction=ctx.direction,
        snapshot_1m=ctx.snapshot_1m,
        snapshot_5m=ctx.snapshot_5m,
        snapshot_15m=ctx.snapshot_15m,
        candles_1m=[],
        box_high=ctx.box_high,
        box_low=ctx.box_low,
        signal_score=ctx.signal_score,
    )

    decision = eng._retest_decision(
        ctx,
        candle(interval="1", o="100", h="100", l="100", c="100"),
        Decimal("1"),
    )

    assert decision.structure_stop_price is None
    assert decision.stop_metadata["structure_stop_warning"] == "STRUCTURE_STOP_UNAVAILABLE"


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


def _scout_candles_no_compression():
    candles = []
    for i in range(100):
        candles.append(
            candle(interval="1", open_time_ms=i * 60_000,
                   o="100", h="100.1", l="99.9", c="100")
        )
    for i in range(100, 116):
        candles.append(
            candle(interval="1", open_time_ms=i * 60_000,
                   o="100", h="100.5", l="99.5", c="100")
        )
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


def _scout_candles_loose_compression():
    candles = []
    for i in range(100):
        candles.append(
            candle(interval="1", open_time_ms=i * 60_000,
                   o="100", h="100.5", l="99.5", c="100")
        )
    for i in range(100, 120):
        candles.append(
            candle(interval="1", open_time_ms=i * 60_000,
                   o="100", h="100.45", l="99.55", c="100")
        )
    return candles


def test_scout_compression_respects_configured_ratio(config):
    config.entry.pre_breakout.score_compression_ratio = 0.8
    eng = EntryTimingEngine(config)
    compression = eng._scout_compression(
        _ctx(candles_1m=_scout_candles_loose_compression())
    )

    assert Decimal("0.8") < compression.ratio < Decimal("1")
    assert compression.has_compression is False
    assert compression.mode == "WITHOUT_COMPRESSION"


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
    assert decision.position_fraction == Decimal("0.60")
    assert decision.stop_atr == Decimal("0.8")
    assert decision.score >= Decimal("5")
    assert decision.compression_mode == "WITH_COMPRESSION"
    assert decision.stop_metadata["structure_stop_enabled"] is True


def test_scout_with_compression_score_6_allowed(config):
    eng = EntryTimingEngine(config)
    candles = _scout_candles()
    ctx = _ctx(
        candles_1m=candles, box_high="100.7",
        s1_kwargs={"ema20": "100", "rsi": "64", "volume_ratio": "0.9", "atr": "1"},
    )
    ctx.snapshot_15m = snap(timeframe="15", close="100", ema20="100.05", ema50="100",
                            slope="0.01", atr="1", atr_percent="1.5",
                            volume_ratio="1.0")
    decision = eng.evaluate(ctx)
    assert decision is not None
    assert decision.entry_mode == EntryMode.PRE_BREAKOUT_SCOUT
    assert decision.position_fraction == Decimal("0.60")
    assert decision.score == Decimal("6")
    assert decision.required_score == Decimal("5")
    assert decision.compression_mode == "WITH_COMPRESSION"


def test_scout_with_compression_score_5_allowed(config):
    eng = EntryTimingEngine(config)
    candles = _scout_candles()
    ctx = _ctx(
        candles_1m=candles, box_high="100.8",
        s1_kwargs={"ema20": "100", "rsi": "64", "volume_ratio": "0.8", "atr": "1"},
    )
    ctx.snapshot_15m = snap(timeframe="15", close="100", ema20="100.05", ema50="100",
                            slope="0.01", atr="1", atr_percent="1.5",
                            volume_ratio="1.0")
    decision = eng.evaluate(ctx)
    assert decision is not None
    assert decision.position_fraction == Decimal("0.60")
    assert decision.score == Decimal("5")
    assert decision.required_score == Decimal("5")
    assert decision.compression_mode == "WITH_COMPRESSION"


def test_scout_without_compression_score_7_allowed_smaller_fraction(config):
    eng = EntryTimingEngine(config)
    candles = _scout_candles_no_compression()
    ctx = _ctx(
        candles_1m=candles, box_high="100.6",
        s1_kwargs={"ema20": "100", "rsi": "64", "volume_ratio": "0.8", "atr": "1"},
    )
    decision = eng.evaluate(ctx)
    assert decision is not None
    assert decision.entry_mode == EntryMode.PRE_BREAKOUT_SCOUT
    assert decision.position_fraction == Decimal("0.30")
    assert decision.score == Decimal("7")
    assert decision.required_score == Decimal("7")
    assert decision.compression_mode == "WITHOUT_COMPRESSION"
    assert decision.compression_bonus_applied == Decimal("0")


def test_scout_without_compression_chase_candle_blocked(config):
    eng = EntryTimingEngine(config)
    candles = _scout_candles_no_compression()
    candles[-1] = candle(
        interval="1",
        open_time_ms=119 * 60_000,
        o="100.16",
        h="100.60",
        l="100.15",
        c="100.59",
    )
    ctx = _ctx(
        candles_1m=candles,
        box_high="100.6",
        s1_kwargs={"ema20": "100", "rsi": "64", "volume_ratio": "1.0", "atr": "1"},
    )
    decision = eng.evaluate(ctx)
    assert decision is None
    assert eng.last_no_entry_reason["reason_code"] == "SCOUT_NO_COMPRESSION_CHASE"
    assert eng.last_no_entry_reason["compression_mode"] == "WITHOUT_COMPRESSION"


def test_scout_without_compression_score_6_blocked(config):
    eng = EntryTimingEngine(config)
    candles = _scout_candles_no_compression()
    ctx = _ctx(
        candles_1m=candles, box_high="100.7",
        s1_kwargs={"ema20": "100", "rsi": "64", "volume_ratio": "0.8", "atr": "1"},
    )
    decision = eng.evaluate(ctx)
    assert decision is None
    assert eng.last_no_entry_reason["reason_code"] == "SCOUT_SCORE_TOO_LOW_NO_COMPRESSION"


def test_scout_logs_distance_before_volume_when_both_fail(config):
    eng = EntryTimingEngine(config)
    candles = _scout_candles()
    decision = eng.evaluate(
        _ctx(
            candles_1m=candles,
            box_high="102",
            s1_kwargs={"ema20": "100", "rsi": "55", "volume_ratio": "0.5", "atr": "1"},
        )
    )

    assert decision is None
    assert eng.last_no_entry_reason["reason_code"] == "SCOUT_TOO_FAR_FROM_BOX"
    assert eng.last_no_entry_reason["scout_failed_conditions"][:2] == [
        "SCOUT_TOO_FAR_FROM_BOX",
        "VOLUME_TOO_LOW",
    ]


def test_scout_without_compression_still_respects_anti_chase(config):
    eng = EntryTimingEngine(config)
    candles = _scout_candles_no_compression()
    ctx = _ctx(
        candles_1m=candles, box_high="100.8",
        s1_kwargs={"ema20": "98", "rsi": "55", "volume_ratio": "2.0", "atr": "1"},
    )
    decision = eng.evaluate(ctx)
    assert decision is None
    assert eng.last_no_entry_reason["reason_code"] == "ANTI_CHASE_LONG"
    assert eng.last_no_entry_reason["anti_chase_reason"] == "PRICE_FAR_ABOVE_EMA"
    assert eng.last_no_entry_reason["compression_mode"] == "WITHOUT_COMPRESSION"


def test_retest_tolerance_uses_config(config):
    config.entry.retest_confirm.retest_tolerance_atr = 0.35
    config.entry.enabled_modes.pre_breakout_scout = False
    eng = EntryTimingEngine(config)
    eng.retests.register("BTCUSDT", SignalDirection.LONG, Decimal("100"))
    candles = _flat(5, price="100")
    candles.append(candle(interval="1", o="100.30", h="100.6", l="100.36", c="100.40"))
    decision = eng.evaluate(_ctx(candles_1m=candles, box_high="101"))
    assert decision is None
    assert eng.last_no_entry_reason["reason_code"] == "RETEST_TOO_FAR_FROM_LEVEL"
