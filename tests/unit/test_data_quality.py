"""Tests for the Data Quality Guard (impl doc §15)."""

from decimal import Decimal

from packages.core.models import IndicatorSnapshot
from packages.guards import DataQualityGuard


def _base_kwargs(now_ms=100_000):
    return dict(
        now_ms=now_ms,
        last_kline_ms=now_ms - 1000,
        last_ticker_ms=now_ms - 500,
        last_orderbook_ms=now_ms - 500,
        missing_candles=0,
        ticker_price=Decimal("100"),
        kline_close=Decimal("100"),
        indicators=IndicatorSnapshot(
            symbol="BTCUSDT", timeframe="5", close=Decimal("100"),
            atr14=Decimal("1"), rsi14=Decimal("55"), ema20=Decimal("99"), valid=True,
        ),
    )


def test_good_data_passes(config):
    g = DataQualityGuard(config.data_quality)
    assert g.check(**_base_kwargs()) is None


def test_stale_kline_blocks(config):
    g = DataQualityGuard(config.data_quality)
    kw = _base_kwargs()
    kw["last_kline_ms"] = (
        kw["now_ms"] - (config.data_quality.max_kline_delay_sec + 1) * 1000
    )
    assert g.check(**kw) == "KLINE_DELAY"


def test_missing_candles_blocks(config):
    g = DataQualityGuard(config.data_quality)
    kw = _base_kwargs()
    kw["missing_candles"] = 2
    assert g.check(**kw) == "MISSING_CANDLES"


def test_price_divergence_blocks(config):
    g = DataQualityGuard(config.data_quality)
    kw = _base_kwargs()
    kw["ticker_price"] = Decimal("101")  # 1% > 0.3%
    assert g.check(**kw) == "PRICE_DIVERGENCE"


def test_nan_indicator_blocks(config):
    g = DataQualityGuard(config.data_quality)
    kw = _base_kwargs()
    kw["indicators"] = IndicatorSnapshot(
        symbol="BTCUSDT", timeframe="5", close=Decimal("100"), valid=False
    )
    assert g.check(**kw) == "INDICATOR_NAN"


def test_missing_timestamp_blocks(config):
    g = DataQualityGuard(config.data_quality)
    kw = _base_kwargs()
    kw["last_ticker_ms"] = None
    assert g.check(**kw) == "TICKER_DELAY"
