"""Tests for CandleStore (arch doc §6.13)."""

from packages.market_data import CandleStore
from tests.fakes.builders import candle


def test_seed_and_get_confirmed_only():
    store = CandleStore()
    candles = [candle(open_time_ms=i * 300_000) for i in range(5)]
    candles.append(candle(open_time_ms=5 * 300_000, confirmed=False))
    store.seed("BTCUSDT", "5", candles)
    got = store.get("BTCUSDT", "5")
    assert len(got) == 5  # in-progress candle excluded
    assert all(c.confirmed for c in got)
    assert store.current("BTCUSDT", "5") is not None
    assert store.get_with_current("BTCUSDT", "5")[-1].confirmed is False


def test_update_appends_new_confirmed():
    store = CandleStore()
    store.seed("BTCUSDT", "5", [candle(open_time_ms=0)])
    store.update(candle(open_time_ms=300_000, c="101"))
    assert len(store.get("BTCUSDT", "5")) == 2
    assert store.last_closed("BTCUSDT", "5").close.__str__() == "101"


def test_update_replaces_same_open_time():
    store = CandleStore()
    store.seed("BTCUSDT", "5", [candle(open_time_ms=0, c="100")])
    store.update(candle(open_time_ms=0, c="105"))
    got = store.get("BTCUSDT", "5")
    assert len(got) == 1
    assert got[0].close.__str__() == "105"


def test_in_progress_candle_tracked():
    store = CandleStore()
    store.seed("BTCUSDT", "5", [candle(open_time_ms=0)])
    store.update(candle(open_time_ms=300_000, confirmed=False, c="102"))
    assert store.current("BTCUSDT", "5") is not None
    with_current = store.get_with_current("BTCUSDT", "5")
    assert len(with_current) == 2
    assert not with_current[-1].confirmed


def test_gap_detection():
    store = CandleStore()
    store.seed("BTCUSDT", "5", [candle(open_time_ms=0)])
    # jump two intervals ahead => one missing candle
    store.update(candle(open_time_ms=3 * 300_000))
    assert store.missing_candles("BTCUSDT", "5") == 2


def test_stale_candle_ignored():
    store = CandleStore()
    store.seed(
        "BTCUSDT", "5",
        [candle(open_time_ms=0), candle(open_time_ms=300_000)],
    )
    store.update(candle(open_time_ms=0, c="999"))  # older than last
    got = store.get("BTCUSDT", "5")
    assert len(got) == 2
    assert got[0].close.__str__() != "999"
