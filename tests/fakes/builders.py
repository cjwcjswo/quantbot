"""Helpers to build market data models for tests."""

from __future__ import annotations

from decimal import Decimal

from packages.core.models import Candle, IndicatorSnapshot, MarketTicker, SymbolMeta


def _d(x):
    return None if x is None else Decimal(str(x))


def indicator_snapshot(
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "15",
    close="100",
    ema20=None,
    ema50=None,
    slope=None,
    rsi=None,
    atr=None,
    atr_percent=None,
    volume_ratio=None,
    swing_high=None,
    swing_low=None,
    valid: bool = True,
    ts_ms: int = 0,
) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        close=Decimal(str(close)),
        ema20=_d(ema20),
        ema50=_d(ema50),
        ema20_slope_atr=_d(slope),
        rsi14=_d(rsi),
        atr14=_d(atr),
        atr_percent=_d(atr_percent),
        volume_ratio=_d(volume_ratio),
        swing_high=_d(swing_high),
        swing_low=_d(swing_low),
        valid=valid,
        ts_ms=ts_ms,
    )


def candle(
    *,
    symbol: str = "BTCUSDT",
    interval: str = "5",
    open_time_ms: int = 0,
    o: str | Decimal = "100",
    h: str | Decimal = "101",
    l: str | Decimal = "99",
    c: str | Decimal = "100",
    v: str | Decimal = "1000",
    confirmed: bool = True,
) -> Candle:
    return Candle(
        symbol=symbol,
        interval=interval,
        open_time_ms=open_time_ms,
        open=Decimal(str(o)),
        high=Decimal(str(h)),
        low=Decimal(str(l)),
        close=Decimal(str(c)),
        volume=Decimal(str(v)),
        confirmed=confirmed,
    )


def series_from_closes(
    closes: list[str | Decimal],
    *,
    symbol: str = "BTCUSDT",
    interval: str = "5",
    interval_ms: int | None = None,
    spread: str | Decimal = "1",
    volume: str | Decimal = "1000",
) -> list[Candle]:
    """Build a confirmed candle series with given closes; high/low = close +/- spread."""
    if interval_ms is None:
        interval_ms = int(interval) * 60_000
    sp = Decimal(str(spread))
    out: list[Candle] = []
    prev = Decimal(str(closes[0]))
    for i, raw in enumerate(closes):
        close = Decimal(str(raw))
        out.append(
            Candle(
                symbol=symbol,
                interval=interval,
                open_time_ms=i * interval_ms,
                open=prev,
                high=max(prev, close) + sp,
                low=min(prev, close) - sp,
                close=close,
                volume=Decimal(str(volume)),
                confirmed=True,
            )
        )
        prev = close
    return out


def ticker(
    *,
    symbol: str = "BTCUSDT",
    last: str | Decimal = "100",
    bid: str | Decimal = "99.99",
    ask: str | Decimal = "100.01",
    turnover_24h: str | Decimal = "100000000",
) -> MarketTicker:
    return MarketTicker(
        symbol=symbol,
        last_price=Decimal(str(last)),
        bid_price=Decimal(str(bid)),
        ask_price=Decimal(str(ask)),
        turnover_24h=Decimal(str(turnover_24h)),
    )


def symbol_meta(
    *,
    symbol: str = "BTCUSDT",
    status: str = "Trading",
    quote: str = "USDT",
    tick: str = "0.1",
    step: str = "0.001",
    min_qty: str = "0.001",
    min_notional: str = "5",
    launch_time_ms: int | None = 0,
) -> SymbolMeta:
    return SymbolMeta(
        symbol=symbol,
        base_coin=symbol.replace(quote, ""),
        quote_coin=quote,
        status=status,
        tick_size=Decimal(tick),
        qty_step=Decimal(step),
        min_order_qty=Decimal(min_qty),
        max_order_qty=Decimal("1000000"),
        min_notional=Decimal(min_notional),
        launch_time_ms=launch_time_ms,
    )
