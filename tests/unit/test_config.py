"""Tests for config loading (impl doc §7)."""

import pytest

from packages.config import load_app_config
from packages.config.settings import AppConfig
from packages.core.enums import BotMode, BotState
from packages.core.errors import ConfigError
from apps.api.config import api_settings_from_config


def test_loads_repo_config():
    """The shipped config/quantbot.yaml validates and matches doc defaults."""
    cfg = load_app_config("config/quantbot.yaml")
    assert isinstance(cfg, AppConfig)
    assert cfg.bot.mode == BotMode.LIVE
    assert cfg.bot.start_state == BotState.STANDBY
    assert cfg.paper.initial_balance_usdt == 10000
    assert cfg.orders.live_new_entry_market_order_allowed is False
    assert cfg.risk.account_risk_per_trade_percent == 1.0
    assert cfg.bot.max_symbols_to_watch == 10
    assert cfg.scanner.max_candidates == 10
    assert cfg.orders.scout_order_type == "AGGRESSIVE_LIMIT"
    assert cfg.orders.retest_order_type == "AGGRESSIVE_LIMIT"
    assert cfg.entry.anti_chase.max_rsi_long == 76
    assert cfg.position_protection.max_seconds_position_without_tpsl == 3
    assert cfg.reconciliation.interval_sec_when_flat == 10
    assert cfg.api.app_env == "production"
    assert cfg.entry.pre_breakout.min_score == 5
    assert cfg.risk.high_atr_derisk_threshold_percent == 3.5


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


def test_api_non_secret_settings_come_from_yaml(monkeypatch):
    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv("CORS_ORIGINS", "http://legacy-env.example")
    monkeypatch.setenv("API_TOKEN_DEV", "env-token")

    cfg = load_app_config("config/quantbot.yaml")
    settings = api_settings_from_config(cfg)

    assert settings.api_auth_enabled is False
    assert settings.cors_list == ["http://localhost:8090"]
    assert settings.api_token_dev == "env-token"
