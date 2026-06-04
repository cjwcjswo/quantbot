"""Tests for UniverseManager and symbol_meta rounding (arch doc §6.10, impl §13.1)."""

from decimal import Decimal

from packages.universe import (
    UniverseManager,
    meets_min_notional,
    meets_min_qty,
    round_price_to_tick,
    round_qty_down,
)
from tests.fakes import FakeGateway
from tests.fakes.builders import symbol_meta

_DAY = 24 * 60 * 60 * 1000
_NOW = 1000 * _DAY  # arbitrary "now"


def _universe(config, instruments):
    gw = FakeGateway()
    gw.set_instruments(instruments)
    return UniverseManager(gw, config.universe, now_ms=_NOW)


async def test_filters_non_usdt_and_non_trading(config):
    um = _universe(
        config,
        [
            symbol_meta(symbol="BTCUSDT", launch_time_ms=0),
            symbol_meta(symbol="ETHUSDC", quote="USDC", launch_time_ms=0),
            symbol_meta(symbol="XRPUSDT", status="PreLaunch", launch_time_ms=0),
        ],
    )
    await um.refresh()
    assert um.all_symbols() == ["BTCUSDT"]


async def test_excludes_new_listing(config):
    recent = _NOW - 3 * _DAY  # 3 days old, limit is 14
    um = _universe(
        config,
        [
            symbol_meta(symbol="OLDUSDT", launch_time_ms=0),
            symbol_meta(symbol="NEWUSDT", launch_time_ms=recent),
        ],
    )
    await um.refresh()
    assert um.is_tradable("OLDUSDT")
    assert not um.is_tradable("NEWUSDT")


async def test_exclude_list(config):
    config.universe.exclude_symbols = ["BTCUSDT"]
    um = _universe(
        config,
        [symbol_meta(symbol="BTCUSDT"), symbol_meta(symbol="ETHUSDT")],
    )
    await um.refresh()
    assert um.all_symbols() == ["ETHUSDT"]


def test_round_qty_down():
    assert round_qty_down(Decimal("1.2345"), Decimal("0.001")) == Decimal("1.234")
    assert round_qty_down(Decimal("0.0009"), Decimal("0.001")) == Decimal("0.000")


def test_round_price_to_tick():
    assert round_price_to_tick(Decimal("100.06"), Decimal("0.1")) == Decimal("100.1")
    assert round_price_to_tick(Decimal("100.04"), Decimal("0.1")) == Decimal("100.0")


def test_min_qty_and_notional():
    meta = symbol_meta(min_qty="0.001", min_notional="5")
    assert meets_min_qty(Decimal("0.001"), meta)
    assert not meets_min_qty(Decimal("0"), meta)
    assert meets_min_notional(Decimal("1"), Decimal("100"), meta)
    assert not meets_min_notional(Decimal("0.01"), Decimal("100"), meta)
