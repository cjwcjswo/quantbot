"""Tests for config loading (impl doc §7)."""

import pytest

from packages.config import load_app_config
from packages.config.settings import AppConfig
from packages.core.enums import BotMode, BotState
from packages.core.errors import ConfigError


def test_loads_repo_config():
    """The shipped config/quantbot.yaml validates and matches doc defaults."""
    cfg = load_app_config("config/quantbot.yaml")
    assert isinstance(cfg, AppConfig)
    assert cfg.bot.mode == BotMode.PAPER
    assert cfg.bot.start_state == BotState.STANDBY
    assert cfg.paper.initial_balance_usdt == 10000
    assert cfg.orders.live_new_entry_market_order_allowed is False
    assert cfg.risk.account_risk_per_trade_percent == 1.0
    assert cfg.entry.anti_chase.max_rsi_long == 68
    assert cfg.position_protection.max_seconds_position_without_tpsl == 3
    assert cfg.reconciliation.interval_sec_when_flat == 10


def test_defaults_when_empty(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("", encoding="utf-8")
    cfg = load_app_config(p)
    assert cfg.bot.mode == BotMode.PAPER


def test_missing_file_raises():
    with pytest.raises(ConfigError):
        load_app_config("does/not/exist.yaml")


def test_unknown_key_rejected(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("bot:\n  not_a_real_key: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_app_config(p)
