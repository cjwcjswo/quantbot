"""Optional Bybit read-only smoke tests.

Disabled by default because they require network access and, for account reads,
valid Bybit credentials. Enable explicitly in an operator environment:

    RUN_BYBIT_SMOKE=1 pytest tests/integration/test_bybit_smoke.py
"""

from __future__ import annotations

import os

import pytest

from packages.config import load_app_config, load_secrets
from packages.exchange.bybit_gateway import BybitExchangeGateway

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_BYBIT_SMOKE") != "1",
    reason="set RUN_BYBIT_SMOKE=1 to run Bybit network smoke tests",
)


def _gateway() -> BybitExchangeGateway:
    cfg = load_app_config()
    sec = load_secrets()
    return BybitExchangeGateway(
        api_key=sec.bybit_api_key,
        api_secret=sec.bybit_api_secret,
        testnet=cfg.exchange.use_testnet,
        category=cfg.bot.category,
        quote_coin=cfg.bot.quote_coin,
        recv_window=cfg.exchange.recv_window,
        rest_rate_per_sec=cfg.api_rate_limit.max_rest_requests_per_second,
        order_rate_per_sec=cfg.api_rate_limit.max_order_requests_per_second,
        backoff_base_sec=cfg.api_rate_limit.backoff_base_sec,
        backoff_max_sec=cfg.api_rate_limit.backoff_max_sec,
    )


async def test_bybit_market_read_smoke():
    gw = _gateway()
    instruments = await gw.load_instruments()
    assert instruments
    symbol = instruments[0].symbol
    tickers = await gw.get_tickers()
    assert any(t.symbol == symbol for t in tickers)
    orderbook = await gw.get_orderbook(symbol, depth=1)
    assert orderbook.best_bid is not None
    assert orderbook.best_ask is not None


async def test_bybit_private_read_smoke():
    sec = load_secrets()
    if not sec.bybit_api_key or not sec.bybit_api_secret:
        pytest.skip("Bybit credentials are required for private smoke test")
    gw = _gateway()
    wallet = await gw.get_wallet_balance()
    assert wallet.coin
    await gw.get_positions()
    await gw.get_open_orders()
