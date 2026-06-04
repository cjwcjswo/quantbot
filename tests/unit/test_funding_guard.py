"""Tests for FundingGuard (impl doc §7 funding_guard)."""

from decimal import Decimal

from packages.guards import FundingGuard


def test_allows_when_calm(config):
    g = FundingGuard(config.funding_guard)
    assert g.block_new_entry(
        now_ms=0, next_funding_time_ms=60 * 60_000, funding_rate=Decimal("0.0001")
    ) is None


def test_blocks_inside_funding_window(config):
    g = FundingGuard(config.funding_guard)  # block within 10 min
    assert g.block_new_entry(
        now_ms=0, next_funding_time_ms=5 * 60_000, funding_rate=Decimal("0.0001")
    ) == "FUNDING_WINDOW"


def test_blocks_high_funding_rate(config):
    g = FundingGuard(config.funding_guard)  # block if abs >= 0.05%
    # 0.0006 fraction = 0.06% > 0.05%
    assert g.block_new_entry(
        now_ms=0, next_funding_time_ms=60 * 60_000, funding_rate=Decimal("0.0006")
    ) == "FUNDING_RATE_HIGH"


def test_should_reduce_on_very_high_funding(config):
    g = FundingGuard(config.funding_guard)  # reduce if abs >= 0.10%
    assert g.should_reduce_position(Decimal("0.0012")) is True  # 0.12%
    assert g.should_reduce_position(Decimal("0.0005")) is False


def test_disabled_never_blocks(config):
    config.funding_guard.enabled = False
    g = FundingGuard(config.funding_guard)
    assert g.block_new_entry(
        now_ms=0, next_funding_time_ms=1, funding_rate=Decimal("1")
    ) is None
