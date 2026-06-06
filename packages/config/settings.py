"""Typed configuration models and loaders (impl doc §7).

``AppConfig`` mirrors ``config/quantbot.yaml`` one-to-one. ``Secrets`` reads
infra credentials from the environment / ``.env`` so secrets never live in YAML.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from packages.core.enums import BotMode, BotState
from packages.core.errors import ConfigError


class _Section(BaseModel):
    # Forbid unknown keys so YAML typos surface immediately.
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# Section models (field names match YAML keys exactly).
# --------------------------------------------------------------------------- #
class BotSection(_Section):
    mode: BotMode = BotMode.PAPER
    account_currency: str = "USDT"
    category: str = "linear"
    quote_coin: str = "USDT"
    start_state: BotState = BotState.STANDBY
    max_active_positions: int = 5
    max_symbols_to_watch: int = 20
    heartbeat_interval_sec: int = 5


class ExchangeSection(_Section):
    name: str = "bybit"
    use_testnet: bool = False
    recv_window: int = 5000
    use_pybit: bool = True


class PaperSection(_Section):
    initial_balance_usdt: float = 10000
    all_orders_as_market: bool = True
    market_slippage_percent: float = 0.03
    taker_fee_percent: float = 0.055
    funding_fee_enabled: bool = False


class UniverseSection(_Section):
    include_quote_coin: str = "USDT"
    min_24h_turnover_usdt: float = 50_000_000
    exclude_new_listing_days: int = 14
    exclude_symbols: list[str] = []
    include_symbols: list[str] = []


class ScannerSection(_Section):
    refresh_interval_sec: int = 300
    max_candidates: int = 20
    atr_prefilter_multiple: int = 3
    atr_refresh_budget: int = 30
    atr_cache_ttl_sec: int = 900
    kline_1m_refresh_sec: int = 25
    kline_5m_refresh_sec: int = 120
    kline_15m_refresh_sec: int = 300
    min_atr_percent: float = 0.5
    max_atr_percent: float = 5.0
    max_spread_percent: float = 0.08
    min_orderbook_depth_usdt_0_1_percent: float = 100_000
    min_orderbook_depth_usdt_0_3_percent: float = 300_000


class TrendQualitySection(_Section):
    long_rsi_min_5m: float = 50
    long_rsi_max_5m: float = 68
    short_rsi_min_5m: float = 32
    short_rsi_max_5m: float = 50
    min_ema_gap_percent_15m: float = 0.10
    min_ema20_slope_atr_15m: float = 0.03
    min_close_distance_from_ema20_atr_15m: float = 0.05
    score_gap_high_percent_15m: float = 0.30
    score_slope_high_atr_15m: float = 0.10
    score_volume_high_ratio_5m: float = 1.2
    score_low_atr_percent_5m: float = 3.0


class VolumeSection(_Section):
    min_setup_volume_ratio: float = 0.6
    min_breakout_volume_ratio: float = 1.3
    max_exhaustion_volume_ratio: float = 4.0


class CandleQualitySection(_Section):
    max_rejection_wick_ratio: float = 0.45
    max_opposite_wick_ratio_for_breakout: float = 0.38
    min_body_ratio_for_breakout: float = 0.40
    long_min_close_position_in_range: float = 0.70
    short_max_close_position_in_range: float = 0.30


class EntryEnabledModes(_Section):
    pre_breakout_scout: bool = True
    breakout_confirm: bool = True
    retest_confirm: bool = True


class PreBreakoutEntry(_Section):
    min_score: int = 6
    position_fraction: float = 0.30
    stop_atr: float = 0.7
    min_volume_ratio: float = 0.8
    max_distance_to_box_atr: float = 0.45
    require_compression: bool = False
    compression_bonus_score: int = 2
    compression_min_score: int | None = 6
    no_compression_min_score: int | None = 7
    compression_position_fraction: float | None = 0.30
    no_compression_position_fraction: float | None = 0.20
    long_rsi_min: float = 46
    long_rsi_max: float = 64
    short_rsi_min: float = 36
    short_rsi_max: float = 54
    score_gap_high_percent_15m: float = 0.30
    score_slope_high_atr_15m: float = 0.10
    score_long_rsi_center_min: float = 50
    score_long_rsi_center_max: float = 60
    score_short_rsi_center_min: float = 40
    score_short_rsi_center_max: float = 50
    score_near_box_atr: float = 0.20
    score_mid_box_atr: float = 0.35
    score_compression_ratio: float = 0.8
    score_high_volume_ratio: float = 2.0


class BreakoutConfirmEntry(_Section):
    position_fraction: float = 0.30
    volume_min_ratio: float = 1.3
    require_close_beyond_boundary: bool = True
    close_beyond_boundary_atr: float = 0.03
    stop_atr: float = 1.0


class RetestConfirmEntry(_Section):
    position_fraction: float = 0.40
    retest_tolerance_atr: float = 0.35
    max_wait_candles: int = 10
    stop_atr: float = 1.3


class AntiChaseEntry(_Section):
    enabled: bool = True
    max_rsi_long: float = 70
    min_rsi_short: float = 30
    max_distance_from_ema20_atr: float = 1.5
    max_recent_3_candle_move_atr: float = 2.0
    max_single_candle_move_atr: float = 1.2
    exhaustion_volume_ratio: float = 4.0


class EntrySection(_Section):
    enabled_modes: EntryEnabledModes = EntryEnabledModes()
    pre_breakout: PreBreakoutEntry = PreBreakoutEntry()
    breakout_confirm: BreakoutConfirmEntry = BreakoutConfirmEntry()
    retest_confirm: RetestConfirmEntry = RetestConfirmEntry()
    anti_chase: AntiChaseEntry = AntiChaseEntry()


class RetestAtrPercentTier(_Section):
    max_atr_percent: float
    stop_atr: float


class VolatilityAdaptiveStopSection(_Section):
    enabled: bool = True
    retest_atr_percent_tiers: list[RetestAtrPercentTier] = Field(
        default_factory=lambda: [
            RetestAtrPercentTier(max_atr_percent=0.25, stop_atr=1.0),
            RetestAtrPercentTier(max_atr_percent=0.60, stop_atr=1.3),
            RetestAtrPercentTier(max_atr_percent=999.0, stop_atr=1.5),
        ]
    )


class StructureStopSection(_Section):
    enabled: bool = True
    apply_to_entry_modes: list[str] = Field(
        default_factory=lambda: ["RETEST_CONFIRM"]
    )
    buffer_atr: float = 0.10
    max_stop_distance_atr: float = 1.8
    min_stop_distance_atr: float = 0.5
    use_structure_stop_for_retest: bool = True


class OrdersSection(_Section):
    live_new_entry_market_order_allowed: bool = False
    scout_order_type: str = "LIMIT"
    breakout_order_type: str = "AGGRESSIVE_LIMIT"
    retest_order_type: str = "LIMIT"
    max_slippage_percent: float = 0.05
    limit_order_ttl_sec: int = 10
    scout_limit_order_ttl_sec: int = 30
    retest_limit_order_ttl_sec: int = 20
    limit_reorder_attempts: int = 1
    aggressive_limit_time_in_force: str = "IOC"
    use_reduce_only_for_exits: bool = True
    pre_order_depth_multiple: float = 3.0
    pre_order_depth_band_percent: float = 0.1
    partial_fill_min_ratio_to_keep: float = 0.70
    partial_fill_below_min_action: str = "CLOSE_FILLED_QTY"


class RiskSection(_Section):
    account_risk_per_trade_percent: float = 1.0
    daily_max_loss_percent: float = 5.0
    intraday_drawdown_percent: float = 3.0
    max_symbol_risk_percent: float = 1.0
    max_total_open_risk_percent: float = 5.0
    max_same_direction_positions: int = 4
    min_leverage: int = 1
    scout_max_leverage: int = 3
    breakout_max_leverage: int = 5
    retest_max_leverage: int = 6
    high_quality_max_leverage: int = 8
    high_atr_max_leverage: int = 3
    high_atr_derisk_threshold_percent: float = 3.5
    consecutive_loss_derisk_count: int = 2
    consecutive_loss_max_leverage: int = 3
    daily_loss_derisk_percent: float = 3.0
    daily_loss_max_leverage: int = 2
    min_stop_distance_atr: float = 0.5
    max_stop_distance_atr: float = 1.5
    retest_max_stop_distance_atr: float = 1.8
    isolated_margin: bool = True


class LiquidationGuardSection(_Section):
    min_liquidation_distance_percent: float = 2.0
    min_liquidation_distance_atr: float = 2.0
    block_if_liq_price_inside_stop: bool = True


class TpSlSection(_Section):
    initial_take_profit_r: float = 2.0
    use_exchange_sl: bool = True
    use_exchange_tp: bool = False
    use_exchange_tpsl: bool = True
    tp_trigger_by: str = "LastPrice"
    sl_trigger_by: str = "LastPrice"
    tpsl_mode: str = "Full"


class PositionProtectionSection(_Section):
    stop_mode: str = "EXCHANGE_TPSL"
    require_tpsl_after_entry: bool = True
    max_seconds_position_without_tpsl: int = 3
    emergency_close_if_tpsl_missing: bool = True
    verify_tpsl_after_entry: bool = True
    verify_tpsl_retry_count: int = 3
    verify_tpsl_retry_interval_sec: int = 1
    tpsl_verify_tolerance_percent: float = 0.02


class ScoutManagementSection(_Section):
    enabled: bool = True
    grace_bars: int = 6
    confirmation_boundary_atr: float = 0.03
    confirmation_volume_ratio: float = 1.1
    min_hold_bars_before_defensive_reduce: int = 3
    warning_confirm_bars: int = 2
    max_defensive_reductions: int = 1
    defensive_reduce_fraction: float = 0.50
    invalidate_on_box_mid_reclaim: bool = True
    invalidate_on_ema20_reclaim_bars: int = 2
    long_invalid_rsi_threshold: float = 45
    short_invalid_rsi_threshold: float = 55
    strong_opposite_candle_body_ratio: float = 0.55
    strong_opposite_candle_volume_ratio: float = 1.5
    catastrophic_opposite_candle_body_ratio: float = 0.75
    catastrophic_opposite_candle_volume_ratio: float = 3.0
    catastrophic_opposite_move_atr: float = 1.2
    convert_to_active_on_confirmation: bool = True


class RunnerModeSection(_Section):
    enabled: bool = True
    activate_after_partial_tp: bool = True
    activate_min_r: float = 2.0
    weak_trend_trailing_atr: float = 2.0
    strong_trend_trailing_atr: float = 2.8
    very_strong_trend_trailing_atr: float = 3.2
    strong_trend_min_r: float = 2.0
    very_strong_trend_min_r: float = 5.0
    require_5m_trend_hold: bool = True
    require_1m_ema20_hold: bool = True
    long_min_1m_rsi: float = 50
    short_max_1m_rsi: float = 50
    tighten_on_1m_ema20_break_bars: int = 2
    tighten_on_strong_opposite_candle: bool = True
    min_trailing_update_interval_sec: int = 5
    min_trailing_improvement_atr: float = 0.20
    log_post_exit_mfe: bool = True
    post_exit_mfe_windows_min: list[int] = Field(default_factory=lambda: [5, 15, 30])


class PositionSection(_Section):
    partial_take_profit_r: float = 2.0
    partial_take_profit_fraction: float = 0.50
    trailing_start_r: float = 2.0
    trailing_atr_multiplier: float = 2.0
    trailing_extended_after_r: float = 5.0
    trailing_extended_atr_multiplier: float = 2.5
    max_holding_minutes: int = 180
    sync_exchange_sl_with_trailing: bool = True
    min_exchange_sl_update_interval_sec: int = 5
    runner_mode: RunnerModeSection = RunnerModeSection()
    scout_management: ScoutManagementSection = ScoutManagementSection()


class StagnationScout(_Section):
    max_bars_without_breakout: int = 8


class StagnationBreakout(_Section):
    reduce_after_bars: int = 5
    reduce_fraction: float = 0.5
    max_bars_without_1r: int = 10


class StagnationRetest(_Section):
    tighten_after_bars: int = 6
    max_bars_without_1r: int = 12


class StagnationExitSection(_Section):
    enabled: bool = True
    pre_breakout_scout: StagnationScout = StagnationScout()
    breakout_confirm: StagnationBreakout = StagnationBreakout()
    retest_confirm: StagnationRetest = StagnationRetest()


class CooldownSection(_Section):
    symbol_cooldown_after_loss_min: int = 15
    symbol_cooldown_after_2_losses_min: int = 60
    global_cooldown_after_3_losses_min: int = 30
    entry_mode_cooldown_after_loss_min: int = 20


class GlobalKillSwitchSection(_Section):
    daily_loss_percent: float = 5.0
    intraday_drawdown_percent: float = 3.0
    consecutive_losses: int = 4
    order_failures_in_5min: int = 3
    websocket_disconnects_in_10min: int = 3
    unexpected_position_mismatch_count: int = 1
    emergency_close_failure_count: int = 1
    max_slippage_percent_breach_count: int = 2


class ReconciliationSection(_Section):
    interval_sec_when_flat: int = 10
    interval_sec_when_position_open: int = 3
    interval_sec_after_order_event: int = 1
    run_on_startup: bool = True
    run_after_ws_reconnect: bool = True
    run_after_order_timeout: bool = True
    source_of_truth: str = "exchange"


class ManualInterventionSection(_Section):
    allow_external_orders: bool = True
    pause_new_entries_on_external_change: bool = True
    pause_seconds_after_external_change: int = 60
    adopt_external_positions: bool = True
    manage_adopted_positions: bool = False
    cancel_external_open_orders: bool = False


class DataQualitySection(_Section):
    max_kline_delay_sec: int = 30
    max_ticker_delay_sec: int = 30
    max_orderbook_delay_sec: int = 3
    max_missing_candles: int = 1
    block_if_candle_gap_detected: bool = True
    max_ticker_kline_price_divergence_percent: float = 0.3


class ClockSyncSection(_Section):
    max_time_drift_ms: int = 500
    sync_interval_sec: int = 60
    block_trading_if_drift_ms_above: int = 1000


class ApiRateLimitSection(_Section):
    max_rest_requests_per_second: int = 2
    max_order_requests_per_second: int = 2
    backoff_base_sec: int = 1
    backoff_max_sec: int = 30


class ApiSection(_Section):
    app_env: str = "local"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    api_auth_enabled: bool = False
    heartbeat_alive_sec: int = 15
    api_run_maintenance: bool = True


class FundingGuardSection(_Section):
    enabled: bool = True
    block_new_entries_before_funding_min: int = 10
    block_if_abs_funding_rate_percent_above: float = 0.05
    reduce_position_if_abs_funding_rate_percent_above: float = 0.10


class SymbolStatusSection(_Section):
    refresh_interval_sec: int = 300
    block_if_status_not_trading: bool = True


class AppConfig(_Section):
    """Aggregate of every config section in ``config/quantbot.yaml``."""

    bot: BotSection = BotSection()
    exchange: ExchangeSection = ExchangeSection()
    paper: PaperSection = PaperSection()
    universe: UniverseSection = UniverseSection()
    scanner: ScannerSection = ScannerSection()
    trend_quality: TrendQualitySection = TrendQualitySection()
    volume: VolumeSection = VolumeSection()
    candle_quality: CandleQualitySection = CandleQualitySection()
    entry: EntrySection = EntrySection()
    volatility_adaptive_stop: VolatilityAdaptiveStopSection = (
        VolatilityAdaptiveStopSection()
    )
    structure_stop: StructureStopSection = StructureStopSection()
    orders: OrdersSection = OrdersSection()
    risk: RiskSection = RiskSection()
    liquidation_guard: LiquidationGuardSection = LiquidationGuardSection()
    tpsl: TpSlSection = TpSlSection()
    position_protection: PositionProtectionSection = PositionProtectionSection()
    position: PositionSection = PositionSection()
    stagnation_exit: StagnationExitSection = StagnationExitSection()
    cooldown: CooldownSection = CooldownSection()
    global_kill_switch: GlobalKillSwitchSection = GlobalKillSwitchSection()
    reconciliation: ReconciliationSection = ReconciliationSection()
    manual_intervention: ManualInterventionSection = ManualInterventionSection()
    data_quality: DataQualitySection = DataQualitySection()
    clock_sync: ClockSyncSection = ClockSyncSection()
    api_rate_limit: ApiRateLimitSection = ApiRateLimitSection()
    api: ApiSection = ApiSection()
    funding_guard: FundingGuardSection = FundingGuardSection()
    symbol_status: SymbolStatusSection = SymbolStatusSection()


class Secrets(BaseSettings):
    """Infra credentials from environment / .env (never in YAML)."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    bybit_api_key: str = ""
    bybit_api_secret: str = ""
    database_url: str = "postgresql+asyncpg://quantbot:quantbot@localhost:5432/quantbot"
    redis_url: str = "redis://localhost:6379/0"
    quantbot_config: str = "config/quantbot.yaml"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"Config root must be a mapping, got {type(data).__name__}")
    return data


def load_app_config(path: str | os.PathLike[str] | None = None) -> AppConfig:
    """Load and validate ``AppConfig`` from a YAML file.

    Resolution order for ``path``: explicit arg -> ``QUANTBOT_CONFIG`` env ->
    ``config/quantbot.yaml``.
    """
    resolved = Path(
        path or os.environ.get("QUANTBOT_CONFIG", "config/quantbot.yaml")
    )
    raw = _read_yaml(resolved)
    try:
        return AppConfig.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError -> ConfigError
        raise ConfigError(f"Invalid config in {resolved}: {exc}") from exc


def load_secrets() -> Secrets:
    return Secrets()
