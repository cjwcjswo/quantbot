"""Tests for FundingGuard (impl doc §7 funding_guard)."""

from decimal import Decimal

from packages.core.enums import PositionSide, SignalDirection
from packages.guards import FundingGuard


def test_allows_when_calm(config):
    g = FundingGuard(config.funding_guard)
    assert g.block_new_entry(
        now_ms=0,
        next_funding_time_ms=60 * 60_000,
        funding_rate=Decimal("0.0001"),
        direction=SignalDirection.LONG,
    ) is None


def test_blocks_inside_funding_window(config):
    g = FundingGuard(config.funding_guard)  # block within 5 min
    assert g.block_new_entry(
        now_ms=0,
        next_funding_time_ms=5 * 60_000,
        funding_rate=Decimal("-0.0001"),
        direction=SignalDirection.LONG,
    ) == "FUNDING_WINDOW"


def test_blocks_unfavorable_high_funding_rate(config):
    g = FundingGuard(config.funding_guard)  # block if adverse abs >= 0.08%
    # 0.0009 fraction = 0.09% > 0.08%; positive funding is adverse for longs.
    assert g.block_new_entry(
        now_ms=0,
        next_funding_time_ms=60 * 60_000,
        funding_rate=Decimal("0.0009"),
        direction=SignalDirection.LONG,
    ) == "FUNDING_RATE_HIGH"


def test_allows_favorable_high_funding_rate(config):
    g = FundingGuard(config.funding_guard)
    # Positive funding is favorable for shorts, so do not block by abs alone.
    assert g.block_new_entry(
        now_ms=0,
        next_funding_time_ms=60 * 60_000,
        funding_rate=Decimal("0.0009"),
        direction=SignalDirection.SHORT,
    ) is None
    # Negative funding is favorable for longs.
    assert g.block_new_entry(
        now_ms=0,
        next_funding_time_ms=60 * 60_000,
        funding_rate=Decimal("-0.0009"),
        direction=SignalDirection.LONG,
    ) is None


def test_should_reduce_on_very_high_funding(config):
    g = FundingGuard(config.funding_guard)  # reduce if adverse abs >= 0.12%
    assert g.should_reduce_position(Decimal("0.0013"), PositionSide.LONG) is True
    assert g.should_reduce_position(Decimal("0.0013"), PositionSide.SHORT) is False
    assert g.should_reduce_position(Decimal("-0.0013"), PositionSide.SHORT) is True
    assert g.should_reduce_position(Decimal("0.0005"), PositionSide.LONG) is False


def test_disabled_never_blocks(config):
    config.funding_guard.enabled = False
    g = FundingGuard(config.funding_guard)
    assert g.block_new_entry(
        now_ms=0,
        next_funding_time_ms=1,
        funding_rate=Decimal("1"),
        direction=SignalDirection.LONG,
    ) is None
