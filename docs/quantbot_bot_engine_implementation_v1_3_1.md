# QuantBot Bot Engine 구현 문서 v1.3.1
## 실전 운영 방어막 포함 최종 개발 프롬프트

## 1. 문서 목적

이 문서는 AI 개발 에이전트가 QuantBot의 Bot Engine을 실제로 구현할 수 있도록 작성된 최종 개발 명세다.

v1.3의 구현 범위는 다음으로 제한한다.

```text
Bybit USDT Perpetual 기반 추세 추종 봇
PAPER / LIVE 2가지 모드 지원
PAPER는 실제 Bybit 시장 데이터를 사용하되 가상 자산으로 시장가 체결 시뮬레이션
LIVE는 실제 Bybit 계좌와 주문 사용
RangeBot, Shock Reversal 등은 향후 AddOn 전략으로 추가 가능하게 구조만 준비
```

본 문서에서 가장 중요한 원칙은 다음과 같다.

```text
1. 모호한 표현 금지
2. 모든 진입/청산/예외 조건은 숫자와 공식으로 정의
3. 신규 진입은 추격 시장가를 금지
4. LIVE 진입 시 Stop Loss와 Take Profit 보호를 반드시 설정/확인
5. Bybit 실제 상태를 주기적으로 동기화하되, 수동 개입 포지션은 봇이 자동 관리하지 않음
6. 프로그램 시작만으로 거래하지 않고 STANDBY 상태에서 사용자 START 명령을 기다림
```

---

# 2. 운영 모드

## 2.1 PAPER 모드

PAPER 모드는 실제 Bybit 시장 데이터를 사용하지만, 실제 주문은 넣지 않는다.

```text
시장 데이터: Bybit 실시간 데이터 사용
자산: 내부 가상 자산 사용
주문: 전부 시장가 체결 시뮬레이션
주문 타입: PAPER에서는 LIMIT/AGGRESSIVE_LIMIT 시뮬레이션 금지
체결 가격: 현재 best ask/bid 또는 최신 ticker 가격 기준
수수료/슬리피지: 설정값으로 반영
```

PAPER 모드는 실제 체결 우선순위나 호가 대기열을 정교하게 재현하지 않는다. 목적은 전략 로직, 리스크 관리, 포지션 관리, 이벤트 저장, 상태 머신, 대시보드 연동 검증이다.

### PAPER 체결 규칙

롱 진입:

```text
fill_price = current_best_ask * (1 + paper.market_slippage_percent / 100)
```

숏 진입:

```text
fill_price = current_best_bid * (1 - paper.market_slippage_percent / 100)
```

롱 청산:

```text
fill_price = current_best_bid * (1 - paper.market_slippage_percent / 100)
```

숏 청산:

```text
fill_price = current_best_ask * (1 + paper.market_slippage_percent / 100)
```

설정값:

```yaml
paper:
  initial_balance_usdt: 10000
  all_orders_as_market: true
  market_slippage_percent: 0.03
  taker_fee_percent: 0.055
  funding_fee_enabled: false
```

PAPER에서는 모든 주문이 즉시 체결된다. 단, 아래 조건에서는 PAPER 주문도 거절한다.

```text
Data Quality Guard 실패
RiskManager 거절
Symbol Status Guard 실패
Spread/Depth Guard 실패
일일 손실 제한 도달
Bot state가 RUNNING이 아님
```

---

## 2.2 LIVE 모드

LIVE 모드는 실제 Bybit 계좌와 주문을 사용한다.

LIVE 모드에서 신규 진입 주문은 다음 주문 타입만 허용한다.

```text
LIMIT
AGGRESSIVE_LIMIT
```

LIVE 모드에서 신규 진입 시장가 주문은 금지한다.

```text
신규 진입 MARKET 금지
손절/긴급청산 reduce-only MARKET 허용
```

LIVE 주문은 Bybit V5 API와 공식 Python SDK인 `pybit`를 사용한다. 단, 내부 모듈이 `pybit`를 직접 호출하지 않고 `ExchangeGateway`를 통해서만 호출해야 한다.

---

# 3. Bot State Machine

프로그램이 시작되었다고 바로 매매를 시작하면 안 된다.

기본 상태 흐름:

```text
BOOTING
→ STANDBY
```

사용자가 START 명령을 내렸을 때만 다음으로 진행한다.

```text
STANDBY
→ START_REQUESTED
→ SYNCING
→ READY
→ RUNNING
```

## 3.1 상태 정의

```text
BOOTING:
프로그램 초기화 중. 거래 금지.

STANDBY:
프로그램은 실행 중이지만 사용자 START 명령 전. 신규 진입 금지. 기존 포지션 자동 관리 금지.

START_REQUESTED:
사용자가 START 명령을 보낸 상태. 설정 검증 시작.

SYNCING:
Bybit 실제 상태, DB 상태, Redis 상태를 동기화 중. 신규 진입 금지.

READY:
동기화와 사전 검증 완료. START 요청 컨텍스트가 유효한 경우에만 RUNNING으로 전환 가능.

RUNNING:
신규 진입, 포지션 관리, 주문 실행 가능.

PAUSED:
사용자 또는 시스템에 의해 신규 진입 중지. 봇이 생성한 기존 포지션은 관리 가능.

RISK_LOCKED:
리스크 제한으로 신규 진입 중지. 수동 해제 전 신규 진입 금지.

RECONCILING:
상태 불일치 또는 WebSocket 재연결 후 동기화 중. 신규 진입 금지.

ORDER_LOCKED:
주문 실패/주문 상태 불명확으로 신규 주문 중지. 청산/조회/동기화만 허용.

EMERGENCY_STOP:
심각한 장애. 신규 진입 금지. 설정에 따라 봇 관리 포지션 긴급 청산.

STOPPING:
종료 절차 진행 중. 신규 진입 금지.

STOPPED:
완전 정지.
```

## 3.2 자동 시작 금지

프로그램 시작 후 자동으로 RUNNING으로 전환하면 안 된다.

```text
BOOTING → STANDBY까지만 자동 허용
STANDBY → RUNNING은 사용자 START 명령이 있어야만 가능
```

---

# 4. Bybit 동기화 정책

## 4.1 기본 원칙

Bybit 실제 상태를 최종 진실로 본다.

```text
source_of_truth = Bybit
```

봇 내부 상태는 매 주기마다 Bybit 상태에 맞춰 보정한다.

단, Bybit 앱이나 외부에서 수동으로 생성한 포지션/주문은 비상 개입으로 간주한다. 봇은 이를 자동 전략 관리 대상으로 삼지 않는다.

```text
수동 개입 감지
→ 내부 상태를 Bybit에 맞춰 동기화
→ 봇 신규 진입 일시 중지
→ 수동 포지션은 봇이 SL/TP/트레일링/시간손절로 관리하지 않음
```

## 4.2 동기화 주기

```yaml
reconciliation:
  interval_sec_when_flat: 10
  interval_sec_when_position_open: 3
  interval_sec_after_order_event: 1
  run_on_startup: true
  run_after_ws_reconnect: true
  run_after_order_timeout: true
  source_of_truth: "exchange"
```

## 4.3 수동 개입 정책

```yaml
manual_intervention:
  allow_external_orders: true
  pause_new_entries_on_external_change: true
  pause_seconds_after_external_change: 60
  adopt_external_positions: true
  manage_adopted_positions: false
  cancel_external_open_orders: false
```

의미:

```text
allow_external_orders:
Bybit 앱 수동 주문 가능. 단, 비상 개입으로 간주.

pause_new_entries_on_external_change:
수동 주문/수동 청산/외부 포지션 변경 감지 시 신규 진입 중지.

pause_seconds_after_external_change:
외부 변경 감지 후 60초 동안 신규 진입 금지.

adopt_external_positions:
외부 포지션을 내부 상태에 표시하고 DB에 기록.

manage_adopted_positions:
false. 봇은 외부 포지션에 SL/TP/트레일링/시간손절을 적용하지 않음.

cancel_external_open_orders:
false. 비상 수동 주문은 봇이 임의 취소하지 않음.
```

## 4.4 외부 포지션 처리

내부에는 포지션 없음, Bybit에는 포지션 있음:

```text
1. external_position_detected 이벤트 저장
2. 내부 PositionRegistry에 source=EXTERNAL로 등록
3. 신규 진입 60초 중지
4. 해당 포지션은 봇 자동 관리 대상에서 제외
5. 대시보드에 EXTERNAL 포지션으로 표시
```

내부에는 봇 포지션 있음, Bybit 수량이 변경됨:

```text
1. position_quantity_mismatch 이벤트 저장
2. Bybit 수량 기준으로 내부 수량을 즉시 보정
3. 신규 진입 60초 중지
4. 수량 감소가 감지되면 수동 부분청산으로 기록
5. 수량 증가가 감지되면 수동 추가진입으로 기록
6. 증가된 수량은 봇 내부 포지션 수량에 그대로 반영
7. 평균 진입가는 Bybit position avgPrice 기준으로 보정
8. 기존 TP/SL이 Bybit 실제 포지션 수량 전체에 적용되어 있는지 재검증
9. TP/SL 수량 또는 설정이 실제 포지션과 불일치하면 Set Trading Stop을 재호출하여 전체 수량 기준으로 보호 설정 재동기화
10. TP/SL 재동기화 실패 시 신규 진입 중지 및 EMERGENCY_TPSL_FAILED 이벤트 저장
```

수동 증가분 처리 원칙:

```text
Bybit 앱에서 수동으로 기존 봇 포지션 수량을 증가시킨 경우,
봇은 Bybit 실제 수량을 최종 진실로 보고 내부 포지션 수량에 그대로 반영한다.

단, 이 수동 증가 행위는 신규 전략 신호로 간주하지 않는다.
따라서 entry_mode, signal_score, strategy_reason은 기존 포지션의 값을 유지하고,
manual_added_qty 필드에 증가 수량을 별도로 기록한다.
```

수동 증가 후 필수 재계산:

```text
position_qty = Bybit 실제 수량
avg_entry_price = Bybit avgPrice
manual_added_qty = Bybit 실제 수량 - 기존 내부 수량
remaining_risk_usdt 재계산
liquidation_distance 재계산
current_unrealized_pnl 재계산
TP/SL 보호 상태 재검증
```

주의:

```text
수동 증가로 인해 risk.account_risk_per_trade_percent 또는 max_symbol_risk_percent를 초과할 수 있다.
이 경우 봇은 이미 증가된 포지션을 강제로 줄이지 않는다.
대신 신규 진입을 중지하고 RISK_LIMIT_EXCEEDED_BY_MANUAL_INTERVENTION 이벤트를 저장한다.
```

내부에는 open order 없음, Bybit에는 open order 있음:

```text
1. external_order_detected 이벤트 저장
2. 내부 OrderRegistry에 source=EXTERNAL로 등록
3. 봇은 해당 주문을 취소하지 않음
4. 신규 진입 60초 중지
```

---

# 5. Bybit TP/SL 보호 정책

## 5.1 기본 원칙

LIVE에서 포지션 진입과 동시에 Stop Loss와 Take Profit 보호가 설정되어야 한다.

Bybit V5는 포지션에 TP/SL/Trailing Stop을 설정하는 API를 제공한다. `Set Trading Stop`은 TP/SL 또는 trailing stop을 포지션에 설정하며, 해당 파라미터를 전달하면 Bybit 시스템이 내부 조건부 주문을 생성하고 포지션 종료 시 취소 및 포지션 크기에 맞춰 조정한다.

## 5.2 TP/SL 설정 방식

v1.3 기본 방식:

```text
1. 진입 주문 생성
2. 체결 확인
3. 체결 수량 기준 포지션 확인
4. 즉시 Bybit Set Trading Stop 호출
5. TP/SL 존재 여부 확인
6. TP/SL 확인 성공 후 포지션 ACTIVE
```

포지션 진입 주문 생성 시 Bybit create order 파라미터로 TP/SL을 함께 줄 수 있는 경우에도, 반드시 체결 후 포지션 기준으로 `Set Trading Stop` 또는 포지션 조회를 통해 TP/SL이 실제 설정되었는지 확인한다.

## 5.3 보호 스탑 모드

```yaml
position_protection:
  stop_mode: "EXCHANGE_TPSL"
  require_tpsl_after_entry: true
  max_seconds_position_without_tpsl: 3
  emergency_close_if_tpsl_missing: true
  verify_tpsl_after_entry: true
  verify_tpsl_retry_count: 3
  verify_tpsl_retry_interval_sec: 1
```

의미:

```text
EXCHANGE_TPSL:
Bybit TP/SL 기능을 기본 보호 장치로 사용한다.

require_tpsl_after_entry:
LIVE 포지션은 TP/SL 없이 ACTIVE 상태가 될 수 없다.

max_seconds_position_without_tpsl:
포지션 체결 후 3초 안에 TP/SL 확인 실패 시 긴급 처리.

emergency_close_if_tpsl_missing:
TP/SL 설정 또는 확인 실패 시 reduce-only MARKET으로 포지션 청산 시도.
```

## 5.4 TP/SL 가격 산정

롱:

```text
stop_loss_price = entry_price - ATR * stop_atr_multiplier
take_profit_price = entry_price + (entry_price - stop_loss_price) * 2.0
```

숏:

```text
stop_loss_price = entry_price + ATR * stop_atr_multiplier
take_profit_price = entry_price - (stop_loss_price - entry_price) * 2.0
```

기본 R:R:

```yaml
tpsl:
  initial_take_profit_r: 2.0
  use_exchange_tpsl: true
  tp_trigger_by: "LastPrice"
  sl_trigger_by: "LastPrice"
  tpsl_mode: "Full"
```

## 5.5 TP/SL 검증 실패 처리

TP/SL 설정 실패:

```text
1. 신규 진입 전체 중지
2. 해당 포지션 reduce-only MARKET 청산 시도
3. emergency_close_order 생성
4. EMERGENCY_TPSL_FAILED 이벤트 저장
5. 청산 성공 시 ORDER_LOCKED 상태로 전환
6. 청산 실패 시 EMERGENCY_STOP 상태로 전환
```

TP/SL 확인 실패:

```text
1. 1초 간격으로 최대 3회 재조회
2. 여전히 TP/SL 확인 불가 시 reduce-only MARKET 청산
3. 신규 진입 중지
```

---

# 6. ExchangeGateway

## 6.1 Bybit 연동 방식

Bybit 연동은 공식 V5 API와 공식 Python SDK `pybit`를 사용한다.

단, 프로젝트 내부 모듈은 `pybit`를 직접 호출하지 않는다.

```text
Bot 내부 모듈
→ ExchangeGateway interface
→ BybitExchangeGateway
→ pybit
→ Bybit API
```

## 6.2 필수 메서드

```python
class ExchangeGateway(Protocol):
    async def load_instruments(self) -> list[SymbolMeta]: ...
    async def get_tickers(self) -> list[MarketTicker]: ...
    async def get_kline(self, symbol: str, interval: str, limit: int) -> list[Candle]: ...
    async def get_orderbook(self, symbol: str, depth: int) -> OrderBook: ...
    async def get_wallet_balance(self) -> WalletBalance: ...
    async def get_positions(self) -> list[ExchangePosition]: ...
    async def get_open_orders(self, symbol: str | None = None) -> list[ExchangeOrder]: ...
    async def set_leverage(self, symbol: str, leverage: Decimal) -> None: ...
    async def place_order(self, request: OrderRequest) -> ExchangeOrderResult: ...
    async def cancel_order(self, symbol: str, order_id: str | None, client_order_id: str | None) -> None: ...
    async def set_trading_stop(self, request: TradingStopRequest) -> TradingStopResult: ...
    async def get_position_tpsl(self, symbol: str) -> PositionTpSlState: ...
```

## 6.3 필수 Bybit API 범위

```text
/v5/market/instruments-info
/v5/market/tickers
/v5/market/kline
/v5/market/orderbook
/v5/account/wallet-balance
/v5/position/list
/v5/position/set-leverage
/v5/position/trading-stop
/v5/order/create
/v5/order/cancel
/v5/order/realtime
```

---

# 7. Config

```yaml
bot:
  mode: "PAPER"
  account_currency: "USDT"
  category: "linear"
  quote_coin: "USDT"
  start_state: "STANDBY"
  max_active_positions: 5
  max_symbols_to_watch: 30
  heartbeat_interval_sec: 5

exchange:
  name: "bybit"
  use_testnet: false
  recv_window: 5000
  use_pybit: true

paper:
  initial_balance_usdt: 10000
  all_orders_as_market: true
  market_slippage_percent: 0.03
  taker_fee_percent: 0.055
  funding_fee_enabled: false

universe:
  include_quote_coin: "USDT"
  min_24h_turnover_usdt: 50000000
  exclude_new_listing_days: 14
  exclude_symbols: []
  include_symbols: []

scanner:
  refresh_interval_sec: 300
  max_candidates: 30
  min_atr_percent: 0.5
  max_atr_percent: 5.0
  max_spread_percent: 0.08
  min_orderbook_depth_usdt_0_1_percent: 100000
  min_orderbook_depth_usdt_0_3_percent: 300000

trend_quality:
  min_ema_gap_percent_15m: 0.15
  min_ema20_slope_atr_15m: 0.05
  min_close_distance_from_ema20_atr_15m: 0.10

volume:
  min_setup_volume_ratio: 0.8
  min_breakout_volume_ratio: 1.5
  max_exhaustion_volume_ratio: 4.0

candle_quality:
  max_rejection_wick_ratio: 0.45
  max_opposite_wick_ratio_for_breakout: 0.35
  min_body_ratio_for_breakout: 0.45
  long_min_close_position_in_range: 0.75
  short_max_close_position_in_range: 0.25

entry:
  enabled_modes:
    pre_breakout_scout: true
    breakout_confirm: true
    retest_confirm: true

  pre_breakout:
    min_score: 8
    position_fraction: 0.30
    stop_atr: 0.7

  breakout_confirm:
    position_fraction: 0.30
    volume_min_ratio: 1.5
    require_close_beyond_boundary: true
    close_beyond_boundary_atr: 0.05
    stop_atr: 1.0

  retest_confirm:
    position_fraction: 0.40
    retest_tolerance_atr: 0.25
    max_wait_candles: 8
    stop_atr: 1.0

  anti_chase:
    enabled: true
    max_rsi_long: 68
    min_rsi_short: 32
    max_distance_from_ema20_atr: 1.2
    max_recent_3_candle_move_atr: 1.5
    max_single_candle_move_atr: 1.0

orders:
  live_new_entry_market_order_allowed: false
  scout_order_type: "LIMIT"
  breakout_order_type: "AGGRESSIVE_LIMIT"
  retest_order_type: "LIMIT"
  max_slippage_percent: 0.05
  limit_order_ttl_sec: 10
  limit_reorder_attempts: 1
  aggressive_limit_time_in_force: "IOC"
  use_reduce_only_for_exits: true
  partial_fill_min_ratio_to_keep: 0.70
  partial_fill_below_min_action: "CLOSE_FILLED_QTY"

risk:
  account_risk_per_trade_percent: 1.0
  daily_max_loss_percent: 5.0
  intraday_drawdown_percent: 3.0
  max_symbol_risk_percent: 1.0
  max_total_open_risk_percent: 5.0
  max_same_direction_positions: 4
  min_leverage: 1
  scout_max_leverage: 3
  breakout_max_leverage: 5
  retest_max_leverage: 6
  high_quality_max_leverage: 8
  high_atr_max_leverage: 3
  isolated_margin: true

liquidation_guard:
  min_liquidation_distance_percent: 2.0
  min_liquidation_distance_atr: 2.0
  block_if_liq_price_inside_stop: true

tpsl:
  initial_take_profit_r: 2.0
  use_exchange_tpsl: true
  tp_trigger_by: "LastPrice"
  sl_trigger_by: "LastPrice"
  tpsl_mode: "Full"

position_protection:
  stop_mode: "EXCHANGE_TPSL"
  require_tpsl_after_entry: true
  max_seconds_position_without_tpsl: 3
  emergency_close_if_tpsl_missing: true
  verify_tpsl_after_entry: true
  verify_tpsl_retry_count: 3
  verify_tpsl_retry_interval_sec: 1

position:
  partial_take_profit_r: 2.0
  partial_take_profit_fraction: 0.50
  trailing_start_r: 2.0
  trailing_atr_multiplier: 2.0
  trailing_extended_after_r: 5.0
  trailing_extended_atr_multiplier: 2.5
  max_holding_minutes: 180

stagnation_exit:
  enabled: true
  pre_breakout_scout:
    max_bars_without_breakout: 8
  breakout_confirm:
    reduce_after_bars: 5
    reduce_fraction: 0.5
    max_bars_without_1r: 10
  retest_confirm:
    tighten_after_bars: 6
    max_bars_without_1r: 12

cooldown:
  symbol_cooldown_after_loss_min: 15
  symbol_cooldown_after_2_losses_min: 60
  global_cooldown_after_3_losses_min: 30
  entry_mode_cooldown_after_loss_min: 20

global_kill_switch:
  daily_loss_percent: 5.0
  intraday_drawdown_percent: 3.0
  consecutive_losses: 4
  order_failures_in_5min: 3
  websocket_disconnects_in_10min: 3
  unexpected_position_mismatch_count: 1
  emergency_close_failure_count: 1
  max_slippage_percent_breach_count: 2

reconciliation:
  interval_sec_when_flat: 10
  interval_sec_when_position_open: 3
  interval_sec_after_order_event: 1
  run_on_startup: true
  run_after_ws_reconnect: true
  run_after_order_timeout: true
  source_of_truth: "exchange"

manual_intervention:
  allow_external_orders: true
  pause_new_entries_on_external_change: true
  pause_seconds_after_external_change: 60
  adopt_external_positions: true
  manage_adopted_positions: false
  cancel_external_open_orders: false

data_quality:
  max_kline_delay_sec: 5
  max_ticker_delay_sec: 3
  max_orderbook_delay_sec: 3
  max_missing_candles: 1
  block_if_candle_gap_detected: true
  max_ticker_kline_price_divergence_percent: 0.3

clock_sync:
  max_time_drift_ms: 500
  sync_interval_sec: 60
  block_trading_if_drift_ms_above: 1000

api_rate_limit:
  max_rest_requests_per_second: 5
  max_order_requests_per_second: 2
  backoff_base_sec: 1
  backoff_max_sec: 30

funding_guard:
  enabled: true
  block_new_entries_before_funding_min: 10
  block_if_abs_funding_rate_percent_above: 0.05
  reduce_position_if_abs_funding_rate_percent_above: 0.10

symbol_status:
  refresh_interval_sec: 300
  block_if_status_not_trading: true
```

---

# 8. 추세 추종 전략 조건

## 8.1 롱 후보 조건

롱 후보는 아래 조건을 모두 만족해야 한다.

```text
15m EMA20 > EMA50
(EMA20 - EMA50) / close * 100 >= 0.15
15m EMA20 slope over last 3 candles >= 0.05 ATR
15m close >= EMA20 + 0.10 ATR
5m close > EMA20
5m RSI14 >= 50 and RSI14 <= 68
5m volume_ratio >= 0.8
ATR% >= 0.5 and ATR% <= 5.0
```

## 8.2 숏 후보 조건

숏 후보는 아래 조건을 모두 만족해야 한다.

```text
15m EMA20 < EMA50
(EMA50 - EMA20) / close * 100 >= 0.15
15m EMA20 slope over last 3 candles <= -0.05 ATR
15m close <= EMA20 - 0.10 ATR
5m close < EMA20
5m RSI14 >= 32 and RSI14 <= 50
5m volume_ratio >= 0.8
ATR% >= 0.5 and ATR% <= 5.0
```

---

# 9. 1분봉 추격 진입 방지

## 9.1 Anti-Chase 롱 차단

롱은 아래 중 하나라도 해당하면 신규 진입 금지다.

```text
1m RSI14 >= 68
현재가 >= EMA20 + 1.2 ATR
최근 3개 1m 캔들 누적 상승폭 >= 1.5 ATR
직전 1개 1m 캔들 상승폭 >= 1.0 ATR
volume_ratio >= 4.0 and upper_wick_ratio >= 0.30
close_position_in_range < 0.75
```

## 9.2 Anti-Chase 숏 차단

숏은 아래 중 하나라도 해당하면 신규 진입 금지다.

```text
1m RSI14 <= 32
현재가 <= EMA20 - 1.2 ATR
최근 3개 1m 캔들 누적 하락폭 >= 1.5 ATR
직전 1개 1m 캔들 하락폭 >= 1.0 ATR
volume_ratio >= 4.0 and lower_wick_ratio >= 0.30
close_position_in_range > 0.25
```

---

# 10. Healthy Breakout / Exhaustion Breakout

## 10.1 캔들 계산식

```text
candle_range = high - low
body = abs(close - open)
upper_wick = high - max(open, close)
lower_wick = min(open, close) - low

body_ratio = body / candle_range
upper_wick_ratio = upper_wick / candle_range
lower_wick_ratio = lower_wick / candle_range
close_position_in_range = (close - low) / candle_range
```

`candle_range <= 0`이면 진입 금지.

## 10.2 Healthy Long Breakout

아래 조건을 모두 만족해야 한다.

```text
close > box_high + 0.05 ATR
volume_ratio >= 1.5
volume_ratio < 4.0
body_ratio >= 0.45
upper_wick_ratio <= 0.35
close_position_in_range >= 0.75
Anti-Chase Long 통과
```

## 10.3 Healthy Short Breakout

아래 조건을 모두 만족해야 한다.

```text
close < box_low - 0.05 ATR
volume_ratio >= 1.5
volume_ratio < 4.0
body_ratio >= 0.45
lower_wick_ratio <= 0.35
close_position_in_range <= 0.25
Anti-Chase Short 통과
```

## 10.4 Exhaustion Breakout

롱 Exhaustion:

```text
volume_ratio >= 4.0
or upper_wick_ratio >= 0.35
or close_position_in_range < 0.75
or 최근 3개 1m 캔들 누적 상승폭 >= 1.5 ATR
```

숏 Exhaustion:

```text
volume_ratio >= 4.0
or lower_wick_ratio >= 0.35
or close_position_in_range > 0.25
or 최근 3개 1m 캔들 누적 하락폭 >= 1.5 ATR
```

Exhaustion Breakout 처리:

```text
즉시 진입 금지
Breakout entry 금지
Retest pending만 생성
Retest Confirm 조건이 만족될 때만 진입 가능
```

---

# 11. Entry Mode

## 11.1 Pre-Breakout Scout

position_fraction:

```text
0.30
```

롱 Scout 조건:

```text
Trend Long 후보
1m 박스 상단까지 거리 <= 0.35 ATR
1m 저점 2회 이상 상승
1m RSI14 >= 48 and RSI14 <= 62
최근 20개 평균 True Range < 최근 100개 평균 True Range
volume_ratio >= 1.15 and volume_ratio < 4.0
Anti-Chase Long 통과
```

숏 Scout 조건:

```text
Trend Short 후보
1m 박스 하단까지 거리 <= 0.35 ATR
1m 고점 2회 이상 하락
1m RSI14 >= 38 and RSI14 <= 52
최근 20개 평균 True Range < 최근 100개 평균 True Range
volume_ratio >= 1.15 and volume_ratio < 4.0
Anti-Chase Short 통과
```

## 11.2 Breakout Confirm

position_fraction:

```text
0.30
```

진입 허용:

```text
Healthy Breakout만 허용
Exhaustion Breakout은 진입 금지
```

LIVE 주문 타입:

```text
AGGRESSIVE_LIMIT only
```

PAPER 주문 타입:

```text
MARKET simulation only
```

## 11.3 Retest Confirm

position_fraction:

```text
0.40
```

롱 Retest 조건:

```text
Breakout pending 존재
abs(low - breakout_level) <= 0.25 ATR or abs(close - breakout_level) <= 0.25 ATR
close >= breakout_level
lower_wick_ratio >= 0.30 or close > open
breakout_level 아래에서 2개 1m 캔들 연속 마감 없음
```

숏 Retest 조건:

```text
Breakdown pending 존재
abs(high - breakdown_level) <= 0.25 ATR or abs(close - breakdown_level) <= 0.25 ATR
close <= breakdown_level
upper_wick_ratio >= 0.30 or close < open
breakdown_level 위에서 2개 1m 캔들 연속 마감 없음
```

---

# 12. LIVE 주문 정책

## 12.1 신규 진입 주문

```text
Scout: LIMIT
Breakout: AGGRESSIVE_LIMIT IOC
Retest: LIMIT
MARKET 신규 진입 금지
```

## 12.2 청산 주문

```text
손절: reduce-only MARKET 허용
긴급청산: reduce-only MARKET 허용
부분익절: reduce-only LIMIT 우선, 실패 시 reduce-only MARKET 허용
수동청산 명령: reduce-only MARKET 허용
```

## 12.3 LIMIT 주문 처리

```text
TTL = 10초
0% 체결 → 취소
신호 유효하면 최대 1회 재주문
2회 미체결 → 해당 entry_mode 포기
Scout/Retest는 MARKET 전환 금지
```

## 12.4 AGGRESSIVE_LIMIT 처리

롱:

```text
price = best_ask * (1 + 0.05 / 100)
timeInForce = IOC
```

숏:

```text
price = best_bid * (1 - 0.05 / 100)
timeInForce = IOC
```

부분체결:

```text
filled_qty / requested_qty >= 0.70
→ 체결 수량만 포지션 인정
→ 미체결 잔량 취소

filled_qty / requested_qty < 0.70
→ 미체결 잔량 취소
→ 체결분 reduce-only MARKET 청산
→ exit_reason = PARTIAL_FILL_TOO_SMALL
```

---

# 13. 진입 수량과 레버리지

## 13.1 수량 계산

```text
base_risk_usdt = account_equity * account_risk_per_trade_percent / 100
entry_mode_risk_usdt = base_risk_usdt * position_fraction
stop_distance_percent = abs(entry_price - stop_loss_price) / entry_price
position_notional = entry_mode_risk_usdt / stop_distance_percent
qty = position_notional / entry_price
```

수량 보정:

```text
qtyStep에 맞게 내림
minOrderQty 미만이면 주문 금지
minNotional 미만이면 주문 금지
```

## 13.2 Stop Distance Guard

```text
stop_distance_atr < 0.5 → 진입 금지
stop_distance_atr > 1.5 → 진입 금지
```

## 13.3 레버리지 정책

```text
Scout max leverage = 3x
Breakout max leverage = 5x
Retest max leverage = 6x
고품질 누적 포지션 max leverage = 8x
ATR% > 3.5이면 max leverage = 3x
연속 손실 2회 이상이면 max leverage = 3x
일일 손실 -3% 도달 시 max leverage = 2x or 신규 진입 중지
```

## 13.4 Liquidation Guard

진입 금지:

```text
청산가와 현재가 거리 < 2.0%
청산가와 현재가 거리 < 2.0 ATR
청산가가 stop_loss_price보다 먼저 도달 가능한 위치
```

---

# 14. PositionManager

## 14.1 포지션 ACTIVE 조건

LIVE 포지션은 아래 조건을 모두 만족해야 ACTIVE가 된다.

```text
진입 체결 확인
Bybit position 확인
TP/SL 설정 성공
TP/SL 재조회 확인 성공
내부 PositionRegistry 저장 성공
```

PAPER 포지션은 아래 조건을 만족해야 ACTIVE가 된다.

```text
가상 체결 생성
가상 stop_loss_price 저장
가상 take_profit_price 저장
내부 PositionRegistry 저장 성공
```

## 14.2 부분익절

```text
+2R 도달 시 50% 부분익절
LIVE: reduce-only 주문 사용
PAPER: 시장가 청산 시뮬레이션
```

## 14.3 트레일링

```text
+2R 도달 후 trailing 시작
롱: highest_price - ATR * 2.0
숏: lowest_price + ATR * 2.0
+5R 이후 ATR * 2.5
```

트레일링은 내부 PositionManager가 관리한다. 필요 시 Bybit trailing stop API 연동은 후속 단계에서 구현 가능하다.

## 14.4 Stagnation Exit

Scout:

```text
8개 1m 캔들 안에 Breakout Confirm 없으면 청산
```

Breakout:

```text
5개 1m 캔들 안에 +0.5R 미도달 → 50% 축소
10개 1m 캔들 안에 +1R 미도달 → 전량 청산
```

Retest:

```text
6개 1m 캔들 안에 +0.5R 미도달 → stop tighten
12개 1m 캔들 안에 +1R 미도달 → 전량 청산
```

## 14.5 Scenario Invalid Exit

롱 무효화:

```text
5m close < 5m EMA20
or 1m close가 breakout_level 아래에서 2개 연속 마감
or strong bearish candle 발생
```

strong bearish candle:

```text
close < open
body_ratio >= 0.55
volume_ratio >= 1.5
close_position_in_range <= 0.25
```

숏 무효화:

```text
5m close > 5m EMA20
or 1m close가 breakdown_level 위에서 2개 연속 마감
or strong bullish candle 발생
```

strong bullish candle:

```text
close > open
body_ratio >= 0.55
volume_ratio >= 1.5
close_position_in_range >= 0.75
```

처리:

```text
추가 진입 금지
현재 포지션 50% 축소
다음 3개 1m 캔들 안에 +0.5R 회복 실패 시 전량 청산
```

---

# 15. Data Quality Guard

진입 금지 조건:

```text
최근 1m kline 지연 > 5초
ticker 지연 > 3초
orderbook 지연 > 3초
missing candle > 1
ticker와 kline close 괴리 > 0.3%
ATR/RSI/EMA 중 하나라도 NaN
```

---

# 16. Pre-order Check

LIVE 주문 직전 다시 검사한다.

```text
spread_percent <= 0.08
expected_slippage_percent <= 0.05
현재가 ±0.1% orderbook depth >= 주문 notional * 3
symbol status == Trading
clock drift <= 1000ms
```

실패 시 주문 금지.

---

# 17. 주문 예외 처리

## 17.1 Order Timeout

```text
order create timeout
→ client_order_id로 주문 조회
→ 주문 존재하면 해당 주문 상태 사용
→ 주문 없으면 새 client_order_id로 1회 재시도
→ 재시도 실패 시 signal 폐기
```

## 17.2 WebSocket Disconnect

```text
public WS disconnect
→ 신규 진입 중지
→ REST로 ticker/kline 보충
→ 복구 후 SYNCING

private WS disconnect
→ 신규 진입 중지
→ REST로 positions/open orders 조회
→ reconciliation 완료 후 RUNNING 복귀
```

## 17.3 Stop/TP 설정 실패

```text
TP/SL 설정 실패
→ 신규 진입 중지
→ 해당 포지션 reduce-only MARKET 청산
→ 청산 실패 시 EMERGENCY_STOP
```

---

# 18. PnL 기준

일일 손실 제한은 아래 기준으로 계산한다.

```text
daily_net_pnl = realized_pnl + unrealized_pnl - fees - funding_fees
```

갱신 주기:

```text
포지션 없음: 10초
포지션 있음: 3초
주문/체결 직후: 즉시
```

---

# 19. 구현 체크리스트

## Phase 1. Core

- [x] Config v1.3 작성
- [x] Bot State Machine 구현
- [x] STANDBY 시작 정책 구현
- [x] PAPER/LIVE 모드 분리
- [x] 공통 모델 정의
- [x] Decimal 기반 수량/가격 계산

## Phase 2. Exchange

- [x] ExchangeGateway Protocol 작성
- [x] BybitExchangeGateway 구현
- [x] pybit HTTP/WebSocket 연동
- [x] instruments-info 조회
- [x] ticker/kline/orderbook 조회
- [x] wallet/position/open orders 조회
- [x] set leverage 구현
- [x] place order 구현
- [x] set trading stop 구현
- [x] position TP/SL 조회/검증 구현

## Phase 3. Runtime Safety

- [x] Redis runtime lock
- [x] reconciliation 10초/3초/1초 정책
- [x] manual intervention 감지
- [x] external position 등록
- [x] external order 등록
- [x] Global Kill Switch
- [x] Data Quality Guard
- [x] Clock Sync Guard
- [x] API Rate Limit Guard

## Phase 4. Market / Indicators

- [x] UniverseManager
- [x] SymbolScanner
- [x] CandleStore
- [x] IndicatorEngine
- [x] EMA20/EMA50
- [x] RSI14
- [x] ATR14
- [x] Volume Ratio
- [x] Swing High/Low

## Phase 5. Strategy / Entry

- [x] TrendFollowingStrategy
- [x] Anti-Chase
- [x] Healthy Breakout
- [x] Exhaustion Breakout
- [x] Pre-Breakout Scout
- [x] Breakout Confirm
- [x] Retest Confirm
- [x] Pending Retest State

## Phase 6. Risk / Orders

- [x] Position sizing
- [x] Stop Distance Guard
- [x] Leverage policy
- [x] Liquidation Guard
- [x] Pre-order Check
- [x] LIVE LIMIT 주문
- [x] LIVE AGGRESSIVE_LIMIT 주문
- [x] LIVE 신규 MARKET 금지
- [x] PAPER 전 주문 MARKET 시뮬레이션
- [x] Partial Fill 정책
- [x] Order timeout 복구
- [x] Idempotent client_order_id

## Phase 7. Position

- [x] LIVE 진입 후 TP/SL 설정
- [x] TP/SL 검증 실패 시 emergency close
- [x] PAPER 가상 TP/SL 저장
- [x] 부분익절
- [x] 트레일링
- [x] Stagnation Exit
- [x] Scenario Invalid Exit
- [x] Max Holding Time
- [x] Cooldown

## Phase 8. Logging / Tests

- [x] signal 로그
- [x] order 로그
- [x] fill 로그
- [x] position 로그
- [x] reconciliation 로그
- [x] manual intervention 로그
- [x] emergency 로그
- [x] unit tests
- [x] integration tests
- [x] PAPER end-to-end test

---

# 20. 구현 완료 기준

v1.3 구현 완료 기준:

```text
프로그램 시작 후 STANDBY 상태로 대기한다.
START 명령 전 신규 진입이 불가능하다.
PAPER 모드는 실제 Bybit 시장 데이터와 가상 시장가 체결로 동작한다.
LIVE 모드는 신규 진입 시장가를 사용하지 않는다.
LIVE 진입 후 3초 안에 TP/SL이 설정 및 확인된다.
TP/SL 확인 실패 시 포지션을 emergency close한다.
Bybit 실제 상태와 내부 상태를 10초/3초/1초 주기로 동기화한다.
Bybit 앱 수동 주문은 외부 개입으로 기록하고, 기존 봇 포지션 수량 증가 시 Bybit 실제 수량을 내부 포지션에 그대로 반영한다.
Healthy Breakout만 진입하고 Exhaustion Breakout은 Retest pending만 생성한다.
1분봉 고점 롱/저점 숏 추격 조건을 차단한다.
RiskManager 승인 없는 주문은 실행되지 않는다.
모든 주요 이벤트가 DB에 저장된다.
핵심 테스트가 통과한다.
```
