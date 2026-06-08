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
    assert cfg.risk.account_risk_per_trade_percent == 2.5
    assert cfg.bot.max_symbols_to_watch == 20
    assert cfg.scanner.max_candidates == 20
    assert cfg.scanner.refresh_interval_sec == 240
    assert cfg.scanner.atr_refresh_budget == 10
    assert cfg.scanner.atr_cache_ttl_sec == 1800
    assert cfg.scanner.refresh_5m_snapshots_in_scanner is False
    assert cfg.scanner.kline_1m_refresh_sec == 60
    assert cfg.scanner.kline_5m_refresh_sec == 300
    assert cfg.api_rate_limit.max_rest_requests_per_second == 1
    assert cfg.data_quality.max_kline_delay_sec == 90
    assert cfg.orders.partial_fill_min_ratio_to_keep == 0.70
    assert cfg.orders.scout_order_type == "LIMIT"
    assert cfg.orders.breakout_order_type == "AGGRESSIVE_LIMIT"
    assert cfg.orders.retest_order_type == "LIMIT"
    assert cfg.orders.scout_limit_order_ttl_sec == 45
    assert cfg.orders.retest_limit_order_ttl_sec == 20
    assert cfg.entry.anti_chase.max_rsi_long == 70
    assert cfg.position_protection.max_seconds_position_without_tpsl == 3
    assert cfg.reconciliation.interval_sec_when_flat == 10
    assert cfg.api.app_env == "production"
    assert cfg.entry.pre_breakout.min_score == 6
    assert cfg.entry.pre_breakout.position_fraction == 0.40
    assert cfg.entry.pre_breakout.min_stop_distance_percent == 0.45
    assert cfg.entry.pre_breakout.min_volume_ratio == 0.80
    assert cfg.entry.pre_breakout.max_distance_to_box_atr == 0.65
    assert cfg.entry.pre_breakout.require_compression is False
    assert cfg.entry.pre_breakout.compression_min_score == 5
    assert cfg.entry.pre_breakout.no_compression_min_score == 7
    assert cfg.entry.pre_breakout.compression_position_fraction == 0.60
    assert cfg.entry.pre_breakout.no_compression_position_fraction == 0.30
    assert cfg.entry.pre_breakout.no_compression_max_body_ratio == 0.85
    assert cfg.entry.pre_breakout.no_compression_long_max_close_position_in_range == 0.95
    assert cfg.entry.pre_breakout.no_compression_short_min_close_position_in_range == 0.05
    assert cfg.entry.pre_breakout.no_compression_chase_min_volume_ratio == 1.5
    assert cfg.entry.pre_breakout.long_rsi_min == 44
    assert cfg.entry.pre_breakout.long_rsi_max == 68
    assert cfg.entry.pre_breakout.short_rsi_min == 32
    assert cfg.entry.pre_breakout.short_rsi_max == 58
    assert cfg.entry.breakout_confirm.position_fraction == 0.75
    assert cfg.entry.breakout_confirm.require_next_candle_hold is True
    assert cfg.entry.retest_confirm.position_fraction == 0.85
    assert cfg.entry.retest_confirm.stop_atr == 1.3
    assert cfg.volatility_adaptive_stop.enabled is True
    assert cfg.volatility_adaptive_stop.scout_atr_percent_tiers[0].stop_atr == 1.3
    assert cfg.volatility_adaptive_stop.retest_atr_percent_tiers[1].stop_atr == 1.3
    assert cfg.structure_stop.enabled is True
    assert cfg.structure_stop.apply_to_entry_modes == [
        "PRE_BREAKOUT_SCOUT",
        "RETEST_CONFIRM",
    ]
    assert cfg.structure_stop.max_stop_distance_atr == 2.5
    assert cfg.structure_stop.use_structure_stop_for_scout is True
    assert cfg.position.scout_management.enabled is True
    assert cfg.position.scout_management.grace_bars == 6
    assert cfg.position.scout_management.min_hold_bars_before_defensive_reduce == 3
    assert cfg.position.scout_management.warning_confirm_bars == 2
    assert cfg.position.scout_management.max_defensive_reductions == 1
    assert cfg.position.scout_management.catastrophic_opposite_candle_volume_ratio == 3.0
    assert cfg.position.runner_mode.enabled is True
    assert cfg.position.trailing_atr_multiplier == 2.4
    assert cfg.position.trailing_extended_atr_multiplier == 3.0
    assert cfg.position.runner_mode.weak_trend_trailing_atr == 2.0
    assert cfg.position.runner_mode.strong_trend_trailing_atr == 2.8
    assert cfg.position.runner_mode.very_strong_trend_trailing_atr == 3.2
    assert cfg.position.runner_mode.tighten_on_strong_opposite_candle_bars == 2
    assert cfg.position.runner_mode.post_exit_mfe_windows_min == [5, 15, 30]
    assert cfg.stagnation_exit.pre_breakout_scout.max_bars_without_breakout == 10
    assert cfg.stagnation_exit.pre_breakout_scout.min_progress_r == 0.4
    assert cfg.stagnation_exit.breakout_confirm.reduce_after_bars == 7
    assert cfg.stagnation_exit.breakout_confirm.max_bars_without_1r == 14
    assert cfg.stagnation_exit.retest_confirm.tighten_after_bars == 8
    assert cfg.stagnation_exit.retest_confirm.max_bars_without_1r == 16
    assert cfg.stagnation_exit.retest_confirm.scenario_invalid_grace_bars == 3
    assert cfg.risk.scout_max_stop_distance_atr == 3.5
    assert cfg.risk.retest_max_stop_distance_atr == 2.5
    assert cfg.risk.scout_max_leverage == 6
    assert cfg.risk.breakout_max_leverage == 9
    assert cfg.risk.retest_max_leverage == 10
    assert cfg.risk.high_atr_derisk_threshold_percent == 3.5
    assert cfg.risk.min_stop_distance_percent == 0.30
    assert cfg.risk.breakout_min_stop_distance_percent == 0.30
    assert cfg.risk.retest_min_stop_distance_percent == 0.40
    assert cfg.risk.max_stop_distance_atr == 1.8
    assert cfg.risk.thin_stop_distance_percent == 0.35
    assert cfg.risk.thin_stop_max_leverage == 8
    assert cfg.risk.max_symbol_risk_percent == 3.0
    assert cfg.risk.max_total_open_risk_percent == 10.0
    assert cfg.risk.target_notional_percent.enabled is True
    assert cfg.risk.target_notional_percent.scout_no_compression == 30
    assert cfg.risk.target_notional_percent.scout_compression == 50
    assert cfg.risk.target_notional_percent.breakout_confirm == 70
    assert cfg.risk.target_notional_percent.retest_confirm == 80
    assert cfg.risk.target_notional_percent.high_quality == 120
    assert cfg.risk.target_notional_percent.high_quality_min_score == 9
    assert cfg.funding_guard.block_new_entries_before_funding_min == 5
    assert cfg.funding_guard.block_if_abs_funding_rate_percent_above == 0.08
    assert cfg.funding_guard.reduce_position_if_abs_funding_rate_percent_above == 0.12


def test_defaults_when_empty(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("", encoding="utf-8")
    cfg = load_app_config(p)
    assert cfg.bot.mode == BotMode.PAPER
    assert cfg.entry.pre_breakout.position_fraction == 0.40
    assert cfg.entry.pre_breakout.compression_position_fraction == 0.50
    assert cfg.entry.pre_breakout.no_compression_position_fraction == 0.15
    assert cfg.entry.pre_breakout.max_distance_to_box_atr == 0.65
    assert cfg.entry.pre_breakout.compression_min_score == 5
    assert cfg.entry.pre_breakout.no_compression_max_body_ratio == 0.85
    assert cfg.scanner.refresh_5m_snapshots_in_scanner is False
    assert cfg.entry.pre_breakout.long_rsi_min == 44
    assert cfg.entry.pre_breakout.short_rsi_min == 32
    assert cfg.entry.breakout_confirm.position_fraction == 0.60
    assert cfg.entry.retest_confirm.position_fraction == 0.70
    assert cfg.risk.account_risk_per_trade_percent == 1.8
    assert cfg.risk.max_symbol_risk_percent == 2.0
    assert cfg.risk.max_total_open_risk_percent == 7.0
    assert cfg.risk.target_notional_percent.enabled is False
    assert cfg.orders.max_slippage_percent == 0.08
    assert cfg.orders.scout_limit_order_ttl_sec == 45


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
