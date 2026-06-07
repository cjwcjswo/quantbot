"""Tests for MarketDataCollector REST refresh + freshness tracking."""

from decimal import Decimal

from packages.market_data import CandleStore, MarketDataCollector
from tests.fakes import FakeGateway
from tests.fakes.builders import candle, ticker


def _clock():
    box = {"t": 1_000_000}

    def now() -> int:
        return box["t"]

    return now, box


async def test_refresh_klines_feeds_store_and_freshness():
    gw = FakeGateway()
    gw.set_kline(
        "BTCUSDT", "5",
        [candle(open_time_ms=i * 300_000) for i in range(3)],
    )
    store = CandleStore()
    now, box = _clock()
    mdc = MarketDataCollector(gw, store, clock_ms=now)
    await mdc.refresh_klines("BTCUSDT", "5", limit=10)
    assert len(store.get("BTCUSDT", "5")) == 3
    assert mdc.last_kline_ms("BTCUSDT", "5") == 1_000_000


async def test_refresh_klines_skips_when_cache_is_fresh():
    gw = FakeGateway()
    gw.set_kline(
        "BTCUSDT", "1",
        [candle(open_time_ms=i * 60_000, interval="1") for i in range(3)],
    )
    store = CandleStore()
    now, box = _clock()
    mdc = MarketDataCollector(gw, store, clock_ms=now)

    assert await mdc.refresh_klines("BTCUSDT", "1", min_refresh_ms=25_000)
    box["t"] += 10_000
    assert not await mdc.refresh_klines("BTCUSDT", "1", min_refresh_ms=25_000)
    box["t"] += 20_000
    assert await mdc.refresh_klines("BTCUSDT", "1", min_refresh_ms=25_000)

    assert gw.kline_calls == [
        ("BTCUSDT", "1", 200),
        ("BTCUSDT", "1", 200),
    ]


async def test_refresh_tickers_indexed_by_symbol():
    gw = FakeGateway()
    gw.set_ticker(ticker(symbol="BTCUSDT", last="100"))
    gw.set_ticker(ticker(symbol="ETHUSDT", last="2000"))
    mdc = MarketDataCollector(gw, CandleStore())
    await mdc.refresh_tickers()
    assert mdc.ticker("BTCUSDT").last_price == Decimal("100")
    assert mdc.ticker("ETHUSDT").last_price == Decimal("2000")
    assert mdc.last_ticker_ms() is not None


async def test_ingest_candle_updates_store_and_freshness():
    store = CandleStore()
    now, box = _clock()
    mdc = MarketDataCollector(FakeGateway(), store, clock_ms=now)
    mdc.ingest_candle(candle(symbol="BTCUSDT", interval="1", open_time_ms=60_000))

    assert store.last_closed("BTCUSDT", "1") is not None
    assert mdc.last_kline_ms("BTCUSDT", "1") == 1_000_000


async def test_refresh_orderbook():
    from packages.core.models import OrderBook, OrderBookLevel

    gw = FakeGateway()
    gw.set_orderbook(
        OrderBook(
            symbol="BTCUSDT",
            bids=(OrderBookLevel(price=Decimal("99"), size=Decimal("1")),),
            asks=(OrderBookLevel(price=Decimal("101"), size=Decimal("1")),),
        )
    )
    mdc = MarketDataCollector(gw, CandleStore())
    ob = await mdc.refresh_orderbook("BTCUSDT")
    assert ob.best_bid == Decimal("99")
    assert mdc.orderbook("BTCUSDT") is ob
    assert mdc.last_orderbook_ms("BTCUSDT") is not None
