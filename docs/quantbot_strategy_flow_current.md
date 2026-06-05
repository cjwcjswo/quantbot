# QuantBot Strategy Flow - Current Implementation

작성일: 2026-06-05

이 문서는 현재 코드와 `config/quantbot.yaml` 기준으로 QuantBot이 종목을 선정하고, 포지션에 진입하며, 포지션을 보호/관리/청산하는 전체 흐름을 정리한다. 기획 문서의 의도가 아니라 실제 구현 기준이다.

주요 기준 파일:

- `config/quantbot.yaml`
- `apps/bot/runtime/bot_runtime.py`
- `apps/bot/workers/trading_pipeline.py`
- `packages/universe/universe_manager.py`
- `packages/scanner/symbol_scanner.py`
- `packages/strategy/trend_following.py`
- `packages/entry/entry_timing_engine.py`
- `packages/risk/risk_manager.py`
- `packages/execution/order_manager.py`
- `packages/position/protection_manager.py`
- `packages/position/position_manager.py`

## 1. 전체 실행 흐름

봇은 실행 직후 자동 거래를 시작하지 않는다. `bot.start_state`는 `STANDBY`이며, 대시보드에서 START 명령을 받아 `RUNNING` 상태가 되어야 신규 진입을 평가한다.

현재 라이브 설정:

| 항목 | 값 |
| --- | --- |
| 실행 모드 | `LIVE` |
| 거래소 | Bybit linear USDT |
| 시작 상태 | `STANDBY` |
| 최대 활성 포지션 | 5 |
| 감시 종목 수 | 20 |
| 스캐너 갱신 주기 | 180초 |
| 신규 진입 MARKET 주문 | 금지 |

거래 루프는 대략 아래 순서로 실행된다.

1. 전체 티커를 갱신한다.
2. 스캐너 갱신 주기가 지났으면 감시종목을 새로 선정한다.
3. 현재 계좌 equity를 조회한다.
4. 감시 대상 심볼을 순회한다.
5. 이미 보유 중인 봇 포지션이면 먼저 포지션 관리를 수행한다.
6. 포지션이 없으면 신규 진입 후보로 평가한다.
7. 진입하지 않은 심볼은 대시보드 감시종목 탭용 preview를 발행한다.

보유 중인 봇 포지션은 감시 대상 앞쪽에 항상 포함된다. 다만 최종 순회 대상은 `bot.max_symbols_to_watch`인 20개로 제한된다.

## 2. 시장 데이터와 지표

각 심볼 평가에는 1분, 5분, 15분 봉이 사용된다. 각 timeframe은 최대 200개 캔들을 가져와 지표 스냅샷을 만든다.

현재 최소 갱신 간격:

| 데이터 | 갱신 간격 |
| --- | --- |
| 1m kline | 25초 |
| 5m kline | 120초 |
| 15m kline | 300초 |
| scanner ATR cache TTL | 900초 |

계산되는 주요 지표:

| 지표 | 구현 |
| --- | --- |
| EMA20, EMA50 | SMA seed 기반 EMA |
| RSI14 | Wilder smoothing |
| ATR14 | Wilder ATR |
| ATR% | `ATR14 / close * 100` |
| volume_ratio | 마지막 캔들 거래량 / 직전 20개 평균 거래량 |
| swing_high | 최근 20개 캔들의 최고가 |
| swing_low | 최근 20개 캔들의 최저가 |
| EMA20 slope ATR | 최근 3개 EMA20 변화량 / ATR |

필수 지표인 EMA20, EMA50, RSI14, ATR14, volume_ratio 중 하나라도 없으면 `IndicatorSnapshot.valid = false`가 되고 신규 진입은 차단된다.

캔들 품질 판정에는 아래 값이 쓰인다.

- `body_ratio = abs(close - open) / (high - low)`
- `upper_wick_ratio = upper_wick / (high - low)`
- `lower_wick_ratio = lower_wick / (high - low)`
- `close_position_in_range = (close - low) / (high - low)`

캔들 range가 0 이하이면 유효하지 않은 캔들로 처리되어 진입하지 않는다.

## 3. 유니버스 구성

유니버스는 거래소에서 로드한 instrument metadata를 기준으로 구성된다.

심볼이 유니버스에 포함되려면 아래 조건을 만족해야 한다.

| 조건 | 현재 값 |
| --- | --- |
| quote coin | `USDT` |
| status | `Trading` |
| 신규 상장 제외 기간 | 7일 |
| exclude_symbols | 빈 목록 |
| include_symbols | 빈 목록 |

`include_symbols`에 명시된 심볼은 instrument에 존재하면 필터를 우회해 포함될 수 있다.

유니버스 단계는 종목 진입 방향이나 신호를 판단하지 않는다. 거래 가능 후보군만 만든다.

## 4. 감시종목 선정

스캐너는 유니버스에서 거래 가능한 심볼 중 아래 조건을 만족하는 종목을 고른다.

현재 설정:

| 조건 | 값 |
| --- | --- |
| 24h turnover 최소값 | 20,000,000 USDT |
| 최대 spread | 0.10% |
| ATR% 최소값 | 0.15% |
| ATR% 최대값 | 7.0% |
| 최종 후보 수 | 20 |

실제 런타임에서는 먼저 turnover와 spread로 prefilter를 수행한다. prefilter 대상은 `max_candidates * atr_prefilter_multiple`, 즉 현재 20 * 3 = 60개까지다. 그중 `atr_refresh_budget`인 30개씩 15분봉/5분봉 지표를 갱신하고 ATR cache, 15m trend snapshot, 5m volume snapshot을 저장한다. 최종 scanner는 fresh ATR cache가 있는 종목만 대상으로 ATR% 필터를 적용한다.

최종 정렬 기준은 24h turnover 단독이 아니라 `scanner_score` 내림차순이다.

```text
scanner_score =
  turnover_score * 0.30
+ atr_score * 0.25
+ trend_potential_score * 0.25
+ volume_score * 0.10
+ spread_score * 0.10
```

점수 세부 기준:

| 점수 | 기준 |
| --- | --- |
| turnover_score | 통과 후보 내 0-100 정규화 |
| atr_score | 0.5-3.5% = 100, 3.5-5.0% = 70, 그 외 통과 구간 = 40 |
| trend_potential_score | 15m EMA 방향과 slope가 일치하면 100, 약한 방향성 60, 없음 20 |
| volume_score | 5m volume_ratio >= 1.0이면 100, >= 0.6이면 60, 그 외 20 |
| spread_score | spread <= 0.05%이면 100, <= 0.10%이면 70 |

주의할 점:

- `scanner.min_orderbook_depth_usdt_0_1_percent`, `scanner.min_orderbook_depth_usdt_0_3_percent` 설정은 scanner가 orderbook을 전달받을 때만 적용된다.
- 현재 runtime의 scanner 호출은 orderbook을 넘기지 않으므로, orderbook depth 필터는 감시종목 선정 단계가 아니라 진입 직전 pre-order check에서 적용된다.

## 5. 전략 신호 생성

현재 등록된 전략은 `TrendFollowingStrategy` 하나다. `SignalEngine`은 활성 전략을 실행하고, 동일 방향 신호가 여러 개면 점수가 높은 신호만 남긴다. 현재는 전략이 하나뿐이므로 LONG 또는 SHORT 신호가 최대 1개 나온다.

### 5.1 LONG 신호 조건

15분 추세 조건:

- 15m EMA20 > EMA50
- 15m EMA gap >= 0.10%
- 15m EMA20 slope >= 0.03 ATR
- 15m close >= EMA20 + 0.05 ATR

5분 정렬 조건:

- 5m close > EMA20
- 5m RSI14가 50 이상 68 이하
- 5m volume_ratio >= 0.6
- 5m ATR%가 0.15% 이상 7.0% 이하

### 5.2 SHORT 신호 조건

15분 추세 조건:

- 15m EMA20 < EMA50
- 15m EMA gap >= 0.10%
- 15m EMA20 slope <= -0.03 ATR
- 15m close <= EMA20 - 0.05 ATR

5분 정렬 조건:

- 5m close < EMA20
- 5m RSI14가 32 이상 50 이하
- 5m volume_ratio >= 0.6
- 5m ATR%가 0.15% 이상 7.0% 이하

### 5.3 신호 점수

전략 신호 점수는 0에서 10 사이로 계산된다.

| 항목 | 점수 |
| --- | --- |
| 15m EMA gap이 0.30% 이상 | 3점 |
| 15m EMA gap이 기준 이상이나 0.30% 미만 | 2점 |
| 15m EMA20 slope magnitude가 0.10 ATR 이상 | 3점 |
| slope가 기준 이상이나 0.10 ATR 미만 | 2점 |
| 5m volume_ratio가 1.2 이상 | 2점 |
| 5m volume_ratio가 기준 이상이나 1.2 미만 | 1점 |
| 5m ATR%가 3.0% 이하 | 2점 |

이 점수는 신호 우선순위와 Scout 점수의 입력으로 사용된다.

## 6. 신규 진입 전 공통 차단 조건

신호와 진입 모드 평가 전에 아래 guard가 먼저 적용된다.

| Guard | 차단 조건 |
| --- | --- |
| 상태 | state machine이 신규 진입 불가 상태 |
| pause | 외부 변경 등으로 신규 진입 일시 중지 |
| kill switch | 킬스위치 발동 |
| global cooldown | 최근 손실로 글로벌 cooldown 중 |
| symbol cooldown | 해당 심볼 cooldown 중 |
| data quality | kline/ticker 지연, candle gap, 가격 divergence, indicator invalid |
| funding guard | funding 직전 10분 이내 또는 funding rate 과다 |
| symbol status | `Trading`이 아니면 차단 |

현재 data quality 기준:

| 항목 | 값 |
| --- | --- |
| max kline delay | 30초 |
| max ticker delay | 30초 |
| max orderbook delay | 3초 |
| max missing candles | 1 |
| ticker/kline divergence 최대 | 0.5% |

Orderbook 지연 검사는 pre-gate에서 이미 orderbook timestamp가 있을 때만 수행된다. 현재 신규 진입 루프는 주문 직전 pre-order check에서 orderbook을 새로 로드하므로, orderbook 품질은 최종 주문 직전 gate에서 주로 검증된다.

현재 funding guard 기준:

| 항목 | 값 |
| --- | --- |
| funding 전 신규 진입 차단 | 10분 |
| 신규 진입 차단 funding rate | abs(rate) >= 0.05% |
| 포지션 축소 funding rate | abs(rate) >= 0.10% |

## 7. 진입 타이밍 모드

진입 타이밍 엔진은 신호 방향과 1m/5m/15m context를 받아 세 가지 모드 중 하나를 선택한다.

현재 활성화된 모드:

| 모드 | 활성화 |
| --- | --- |
| PRE_BREAKOUT_SCOUT | true |
| BREAKOUT_CONFIRM | true |
| RETEST_CONFIRM | true |

진입 모드 평가는 아래 순서다.

1. 이미 박스를 돌파했는지 확인한다.
2. 돌파했고 healthy breakout이면 `BREAKOUT_CONFIRM`.
3. 돌파했지만 unhealthy/exhaustion이면 retest pending을 등록하고 이번 사이클은 진입하지 않는다.
4. 돌파 상태가 아니라면 기존 retest pending을 확인한다.
5. retest가 확정되면 `RETEST_CONFIRM`.
6. retest가 없거나 확정되지 않으면 Scout 조건을 평가한다.
7. Scout 조건과 점수를 만족하면 `PRE_BREAKOUT_SCOUT`.

### 7.1 박스 기준

박스는 1분봉 지표의 swing 값으로 결정된다.

- LONG 기준 breakout boundary: `box_high = 1m swing_high`
- SHORT 기준 breakdown boundary: `box_low = 1m swing_low`

스윙 값이 없으면 현재 가격으로 대체된다.

### 7.2 Breakout Confirm

Breakout 판정:

- LONG: 마지막 1m close > `box_high + 0.03 * ATR1`
- SHORT: 마지막 1m close < `box_low - 0.03 * ATR1`

참고: `entry.breakout_confirm.require_close_beyond_boundary` 설정값은 현재 코드의 breakout 판정에서 직접 사용되지 않는다. 현재 구현은 항상 boundary 밖 close를 요구한다.

Healthy breakout 조건:

| 조건 | LONG | SHORT |
| --- | --- | --- |
| 1m volume_ratio | 1.3 이상 4.0 미만 | 1.3 이상 4.0 미만 |
| body_ratio | 0.40 이상 | 0.40 이상 |
| 반대 wick | upper_wick_ratio <= 0.38 | lower_wick_ratio <= 0.38 |
| 종가 위치 | close_position_in_range >= 0.70 | close_position_in_range <= 0.30 |
| Anti-chase | 통과 필요 | 통과 필요 |

참고: `entry.breakout_confirm.volume_min_ratio = 1.3` 설정은 존재하지만, 현재 healthy breakout 판정 코드는 `volume.min_breakout_volume_ratio = 1.3`을 사용한다.

통과하면:

- entry mode: `BREAKOUT_CONFIRM`
- position_fraction: 0.30
- stop_atr: 1.0
- 주문 방식: `AGGRESSIVE_LIMIT`
- time in force: `IOC`

Breakout이 발생했지만 healthy 조건을 만족하지 못하면 즉시 진입하지 않고 retest pending을 등록한다.

### 7.3 Retest Confirm

Retest는 unhealthy breakout 이후 등록된 pending state가 있을 때만 가능하다.

현재 설정:

| 항목 | 값 |
| --- | --- |
| retest_tolerance_atr | 0.35 ATR |
| max_wait_candles | 10 |
| position_fraction | 0.40 |
| stop_atr | 1.0 |
| 주문 방식 | LIMIT |
| TTL | 20초 |

Pending retest는 아래 조건에서 만료된다.

- 등록 후 12개 캔들을 초과
- breakout level의 반대편으로 2개 캔들 연속 close

LONG retest 확정 조건:

- candle low 또는 close가 level에서 0.35 ATR 이내
- close가 level 이상
- lower_wick_ratio >= 0.30 또는 양봉 close

SHORT retest 확정 조건:

- candle high 또는 close가 level에서 0.35 ATR 이내
- close가 level 이하
- upper_wick_ratio >= 0.30 또는 음봉 close

### 7.4 Pre-Breakout Scout

Scout는 아직 breakout이 발생하지 않았을 때, 박스 근처에서 선진입하는 모드다.

현재 설정:

| 항목 | 값 |
| --- | --- |
| min_score | 6 |
| position_fraction | 0.30 |
| stop_atr | 0.7 |
| min_volume_ratio | 0.9 |
| max_distance_to_box_atr | 0.45 ATR |
| LONG RSI 범위 | 46-64 |
| SHORT RSI 범위 | 36-54 |
| 주문 방식 | LIMIT |
| TTL | 30초 |

공통 조건:

- ATR20 < ATR100, 즉 단기 변동성이 장기 변동성보다 낮은 compression 필요
- volume_ratio가 0.9 이상 4.0 미만
- Anti-chase 통과 필요

LONG Scout 조건:

- close가 box_high 이하
- box_high - close <= 0.45 ATR
- 최근 4개 캔들에서 rising lows 횟수 >= 2
- RSI14가 46 이상 64 이하

SHORT Scout 조건:

- close가 box_low 이상
- close - box_low <= 0.45 ATR
- 최근 4개 캔들에서 falling highs 횟수 >= 2
- RSI14가 36 이상 54 이하

Scout score는 최대 10점이다.

| 항목 | 점수 |
| --- | --- |
| 15m gap 강함 | 2점 또는 1점 |
| 15m slope 강함 | 2점 또는 1점 |
| 1m RSI 중심권 | 1점 |
| 박스 매우 근접 | 2점 |
| 박스 중간 근접 | 1점 |
| 변동성 compression 강함 | 2점 |
| compression 존재 | 1점 |
| volume_ratio 높음 | 2점 |
| volume_ratio 기준 통과 | 1점 |

현재 `min_score`는 6이며, Scout는 유지하되 과도한 선진입을 줄이도록 이전보다 한 단계 방어적으로 조정되어 있다.

## 8. Anti-Chase 필터

Anti-chase는 고점 추격 LONG 또는 저점 추격 SHORT을 막는다. 필요한 1m 지표가 없으면 fail-safe로 차단한다.

현재 설정:

| 항목 | 값 |
| --- | --- |
| max_rsi_long | 70 |
| min_rsi_short | 30 |
| max_distance_from_ema20_atr | 1.5 ATR |
| max_recent_3_candle_move_atr | 2.0 ATR |
| max_single_candle_move_atr | 1.2 ATR |
| exhaustion volume_ratio | 4.0 |

LONG 차단 조건:

- RSI >= 70
- price >= EMA20 + 1.5 ATR
- 최근 3개 캔들 누적 상승폭 >= 2.0 ATR
- 단일 캔들 상승폭 >= 1.2 ATR
- volume_ratio >= 4.0 이고 upper_wick_ratio >= 0.30
- close_position_in_range < 0.70

SHORT 차단 조건:

- RSI <= 30
- price <= EMA20 - 1.5 ATR
- 최근 3개 캔들 누적 하락폭 <= -2.0 ATR
- 단일 캔들 하락폭 >= 1.2 ATR
- volume_ratio >= 4.0 이고 lower_wick_ratio >= 0.30
- close_position_in_range > 0.30

## 9. 리스크 승인과 포지션 사이징

EntryTimingEngine이 진입 결정을 내리면 RiskManager가 최종 승인한다. 승인되지 않으면 주문은 절대 생성되지 않는다.

### 9.1 Stop Loss와 Take Profit

손절은 진입가와 1m ATR을 기준으로 계산된다.

LONG:

```text
stop_loss = entry - ATR * stop_atr
take_profit = entry + (entry - stop_loss) * 2.0
```

SHORT:

```text
stop_loss = entry + ATR * stop_atr
take_profit = entry - (stop_loss - entry) * 2.0
```

모드별 stop ATR:

| 모드 | stop_atr |
| --- | --- |
| Scout | 0.7 |
| Breakout | 1.0 |
| Retest | 1.0 |

Stop distance guard:

| 조건 | 값 |
| --- | --- |
| 최소 stop distance | 0.5 ATR |
| 최대 stop distance | 1.5 ATR |

계산된 SL/TP는 심볼 tick size에 맞춰 반올림된다.

### 9.2 계좌 단위 제한

신규 진입은 아래 조건에서 거절된다.

| 제한 | 현재 값 |
| --- | --- |
| daily loss limit | 5.0% |
| intraday drawdown limit | 3.0% |
| 최대 활성 포지션 | 5 |
| 동일 심볼 중복 포지션 | 금지 |
| 같은 방향 최대 포지션 수 | 4 |
| 심볼별 risk 최대 | 1.0% |
| 전체 open risk 최대 | 5.0% |

### 9.3 포지션 사이징 공식

기본 공식:

```text
base_risk_usdt = equity * account_risk_per_trade_percent / 100
entry_mode_risk_usdt = base_risk_usdt * position_fraction
stop_distance_percent = abs(entry - stop_loss) / entry
position_notional = entry_mode_risk_usdt / stop_distance_percent
qty = position_notional / entry
```

현재 `account_risk_per_trade_percent`는 1.0%다.

모드별 position fraction:

| 모드 | position_fraction | 의미 |
| --- | --- | --- |
| Scout | 0.30 | 기본 1% 리스크 중 30% 사용 |
| Breakout | 0.30 | 기본 1% 리스크 중 30% 사용 |
| Retest | 0.40 | 기본 1% 리스크 중 40% 사용 |

수량은 거래소 `qty_step`에 맞춰 내림 처리된다. 최소 수량과 최소 notional을 만족하지 못하면 거절된다.

### 9.4 레버리지 정책

레버리지는 “필요한 최소 정수 레버리지”를 고른 뒤 cap으로 제한한다.

```text
needed_leverage = ceil(position_notional / equity)
leverage = clamp(needed_leverage, min_leverage, max_leverage_cap)
```

현재 cap:

| 조건 | cap |
| --- | --- |
| Scout | 3x |
| Breakout | 5x |
| Retest | 6x |
| ATR% > 3.5% | 3x |
| 연속 손실 >= 2 | 3x |
| daily loss >= 3.0% | 2x |
| 최소 레버리지 | 1x |

`high_quality_max_leverage = 8` 설정은 존재하지만, 현재 RiskManager 호출 경로에서는 `high_quality=True`를 전달하지 않으므로 실제 레버리지 cap 산정에는 사용되지 않는다.

### 9.5 청산가 Guard

격리마진 청산가는 사전 추정값으로 계산된다.

LONG:

```text
liq ~= entry * (1 - 1 / leverage + 0.005)
```

SHORT:

```text
liq ~= entry * (1 + 1 / leverage - 0.005)
```

아래 조건을 만족하지 못하면 진입이 거절된다.

| 조건 | 현재 값 |
| --- | --- |
| 청산가와 진입가 거리 | 최소 2.0% |
| 청산가와 진입가 거리 | 최소 2.0 ATR |
| 청산가가 stop 안쪽에 위치 | 차단 |

## 10. 진입 직전 Pre-Order Check

RiskManager 승인 후, 실제 LIVE 주문 전 orderbook을 로드하여 마지막 gate를 통과해야 한다.

현재 기준:

| 조건 | 값 |
| --- | --- |
| symbol status | `Trading` 필요 |
| clock drift | 허용 범위 이내 필요 |
| max spread | 0.10% |
| max expected slippage | 0.08% |
| depth band | mid price 기준 0.1% |
| depth requirement | 주문 notional * 3.0 이상 |

이 단계에서 orderbook depth가 부족하면 `PRE_ORDER:INSUFFICIENT_DEPTH`로 차단된다.

## 11. 주문 실행 정책

LIVE 진입 전에 Bybit leverage를 먼저 설정한다. 그 후 entry mode에 따라 주문 방식이 달라진다.

| 모드 | 주문 타입 | 가격 | TIF/TTL | 실패 처리 |
| --- | --- | --- | --- | --- |
| Scout | LIMIT | BUY=best_bid, SELL=best_ask | GTC, 30초 TTL | 미체결 시 취소 후 1회 재시도 |
| Breakout | AGGRESSIVE_LIMIT | 시장가성 지정가 | IOC | 미체결/작은 부분체결은 거절 |
| Retest | LIMIT | BUY=best_bid, SELL=best_ask | GTC, 20초 TTL | 미체결 시 취소 후 1회 재시도 |

현재 `limit_reorder_attempts = 1`이므로 LIMIT 계열은 총 2번까지 시도된다.

### 11.1 Scout/Retest LIMIT

LIMIT 주문은 지정가로 제출 후 TTL 동안 체결 상태를 poll한다.

- 0% 체결: 주문 취소, 다음 시도 가능
- 일부 체결: 잔량 취소 후 체결된 수량만 포지션으로 유지
- 전체 체결: 정상 진입
- 모든 시도 미체결: `LIMIT_UNFILLED`, 포지션 없음

Scout/Retest LIMIT은 미체결 후 MARKET으로 전환하지 않는다.

### 11.2 Breakout AGGRESSIVE_LIMIT

Breakout은 IOC aggressive limit을 사용한다.

가격:

```text
BUY price = best_ask * (1 + 0.08% / 100)
SELL price = best_bid * (1 - 0.08% / 100)
```

부분체결 정책:

| 상황 | 처리 |
| --- | --- |
| filled_qty <= 0 | `IOC_NO_FILL`, 진입 없음 |
| filled_qty / requested_qty >= 0.70 | 체결 수량만 포지션 유지 |
| filled_qty / requested_qty < 0.70 | 잔량 취소 후 작은 체결분을 reduce-only MARKET으로 청산, 진입 거절 |

LIVE 신규 진입 MARKET 주문은 `live_new_entry_market_order_allowed = false`이므로 금지된다. MARKET은 reduce-only 청산에는 허용된다.

## 12. LIVE 포지션 활성화와 Exchange SL 보호

LIVE 진입 주문이 체결되면 포지션은 바로 ACTIVE가 되지 않는다. 먼저 exchange SL 보호가 성공해야 ACTIVE가 된다. Exchange TP는 사용하지 않고, 부분익절과 trailing은 봇이 관리한다.

흐름:

1. 진입 주문 생성 시 Bybit `stopLoss`를 함께 전달해 exchange SL을 원자적으로 붙인다.
2. 거래소 포지션을 재조회하여 실제 size와 average price를 확인한다.
3. 포지션의 SL 상태를 다시 조회하여 진입 주문에 붙은 보호가 정상 등록됐는지 검증한다.
4. SL이 없거나 가격이 불일치하면 Bybit `set_trading_stop`으로 한 번 보강 설정한다.
5. 검증 성공 시 position status를 `ACTIVE`로 변경한다.
6. 검증 실패 시 emergency close를 수행한다.

현재 보호 설정:

| 항목 | 값 |
| --- | --- |
| TP/SL 방식 | Exchange SL 필수, Exchange TP 비활성화 |
| tpsl_mode | Full |
| trigger_by | LastPrice |
| TP | 내부 PositionManager가 2R 부분익절로 관리 |
| SL | RiskManager가 산정한 stop |
| verify retry | 3회 |
| retry interval | 1초 |
| tolerance | 0.02% |

SL 검증 실패 시:

- `EMERGENCY_TPSL_FAILED` 이벤트 발생
- reduce-only MARKET으로 포지션을 즉시 청산
- 청산 성공 시 `ORDER_LOCKED`
- 청산 실패 시 `EMERGENCY_STOP`

## 13. 포지션 관리와 청산

보유 중인 봇 포지션은 신규 진입보다 먼저 관리된다. `PositionManager.evaluate()`는 매 평가마다 `bars_since_entry`를 증가시키고, 현재 가격 기준 R multiple을 계산한다.

```text
LONG R = (price - avg_entry_price) / initial_risk_per_unit
SHORT R = (avg_entry_price - price) / initial_risk_per_unit
```

### 13.1 Funding Guard 축소

funding rate 절대값이 0.10% 이상이면 포지션의 50%를 reduce-only MARKET으로 축소한다.

### 13.2 최대 보유 시간

`position.max_holding_minutes = 180`이다. 보유 시간이 180분 이상이면 전체 청산한다.

청산 사유: `MAX_HOLDING_TIME`

### 13.3 Trailing Stop

최대 R이 2R 이상이면 trailing이 활성화된다.

기본 trailing:

| 조건 | 계산 |
| --- | --- |
| LONG | highest_price - ATR * 2.0 |
| SHORT | lowest_price + ATR * 2.0 |

확장 trailing:

| 조건 | 계산 |
| --- | --- |
| max R >= 5R LONG | highest_price - ATR * 2.5 |
| max R >= 5R SHORT | lowest_price + ATR * 2.5 |

현재 가격이 trailing stop을 침범하면 전체 청산한다.

청산 사유: `TRAILING_STOP`

현재 `TRAIL_UPDATE`는 내부 `stop_loss_price`를 갱신하고 로그를 저장한다. LIVE에서는 내부 trailing stop이 기존 exchange SL보다 유리한 위치로 이동하면 `position.min_exchange_sl_update_interval_sec = 5`초 간격을 지켜 Bybit exchange SL도 동기화한다. 그래도 최종 trailing 청산 판단은 봇이 가격을 관찰한 뒤 reduce-only MARKET 청산을 실행하는 방식이다.

### 13.4 Scenario Invalidation

아래 조건 중 하나가 발생하면 시나리오 무효화로 판단한다.

1. 5m close가 반대 방향으로 EMA20을 이탈
   - LONG: 5m close < EMA20
   - SHORT: 5m close > EMA20
2. breakout level의 반대편으로 1m close가 2회 연속 발생
   - LONG: close < breakout_level
   - SHORT: close > breakout_level
3. 강한 역방향 1m 캔들
   - body_ratio >= 0.55
   - volume_ratio >= 1.5
   - LONG: 음봉이고 close_position_in_range <= 0.25
   - SHORT: 양봉이고 close_position_in_range >= 0.75

처리:

1. 최초 발생 시 포지션 50%를 reduce-only MARKET으로 축소한다.
2. 3개 bar recovery window를 연다.
3. recovery window 중 R >= 0.5가 되면 회복으로 보고 종료한다.
4. 3개 bar 안에 회복하지 못하면 전체 청산한다.

청산/축소 사유: `SCENARIO_INVALID`

### 13.5 Stagnation Exit

포지션이 기대 방향으로 충분히 진행되지 않으면 mode별로 축소, stop tighten, 또는 전체 청산한다.

Scout:

| 조건 | 처리 |
| --- | --- |
| bars_since_entry >= 8 그리고 max R < 0.5 | 전체 청산 |

Breakout:

| 조건 | 처리 |
| --- | --- |
| bars_since_entry >= 5 그리고 max R < 0.5 | 50% 축소, 1회만 |
| bars_since_entry >= 10 그리고 max R < 1.0 | 전체 청산 |

Retest:

| 조건 | 처리 |
| --- | --- |
| bars_since_entry >= 6 그리고 max R < 0.5 | stop을 현재 stop과 entry의 중간으로 tighten |
| bars_since_entry >= 12 그리고 max R < 1.0 | 전체 청산 |

청산/축소 사유: `STAGNATION`

### 13.6 Partial Take Profit

R이 2.0 이상이고 아직 부분익절을 하지 않았다면 50% 부분익절을 실행한다.

현재 설정:

| 항목 | 값 |
| --- | --- |
| partial_take_profit_r | 2.0 |
| partial_take_profit_fraction | 0.50 |

LIVE 실행 방식:

1. reduce-only LIMIT을 take_profit_price에 제출한다.
2. 완전 체결되면 종료한다.
3. 미체결/부분체결이면 잔량을 취소한다.
4. 남은 수량은 reduce-only MARKET으로 청산한다.

현재 Exchange TP는 비활성화되어 있으므로 2R에서 거래소 Full TP가 먼저 포지션 전체를 닫는 충돌은 제거되어 있다. 2R 부분익절과 이후 trailing은 봇의 PositionManager가 관리한다.

### 13.7 수동 청산

대시보드 또는 API에서 수동 청산 명령이 오면 지정한 percent만큼 reduce-only MARKET으로 청산한다. 포지션이 봇 관리 포지션이 아니거나 ACTIVE/PENDING 상태가 아니면 청산하지 않는다.

청산 사유: `MANUAL_CLOSE`

## 14. 청산 주문 실행

전체 청산 또는 축소는 `TradingService._close()`를 통해 처리된다.

공통 처리:

1. exit side를 결정한다.
   - LONG 청산: SELL
   - SHORT 청산: BUY
2. reduce-only 주문을 제출한다.
3. 체결 수량 기준으로 realized PnL을 계산한다.
4. 포지션 수량을 차감한다.
5. 전체 청산이면 status를 CLOSED로 변경한다.
6. fill, position, trade row를 DB에 저장한다.
7. 손실이면 cooldown과 kill switch의 손실 카운터를 갱신한다.
8. `POSITION_CLOSED` 이벤트를 발행한다.

부분익절은 LIMIT-first, 그 외 일반 축소/전체 청산은 reduce-only MARKET을 사용한다.

## 15. Cooldown

손실 거래가 발생하면 신규 진입을 일정 시간 막는다.

현재 설정:

| 조건 | cooldown |
| --- | --- |
| 한 심볼에서 1회 손실 | 15분 |
| 한 심볼에서 최근 60분 내 2회 손실 | 60분 |
| 글로벌 최근 30분 내 3회 손실 | 30분 |
| 특정 entry mode 손실 | 20분 |

Cooldown은 신규 진입 전 guard에서 검사된다.

## 16. Global Kill Switch

킬스위치는 한번 발동하면 latch되어 신규 진입을 막는다. 수동 reset 전까지 같은 reason을 유지한다.

현재 조건:

| 조건 | 값 |
| --- | --- |
| daily loss | 5.0% |
| intraday drawdown | 3.0% |
| consecutive losses | 4 |
| 5분 내 order failures | 3 |
| 10분 내 websocket disconnects | 3 |
| unexpected position mismatch | 1 |
| emergency close failure | 1 |
| slippage breach | 2 |

킬스위치가 발동하면 신규 진입 guard에서 `KILL_SWITCH:<reason>`으로 차단된다.

## 17. Reconciliation과 수동 개입

거래소가 source of truth다.

현재 reconciliation 설정:

| 상황 | 주기 |
| --- | --- |
| 포지션 없음 | 10초 |
| 포지션 보유 | 3초 |
| 주문 이벤트 직후 | 1초 |
| startup | 실행 |
| WS reconnect 후 | 실행 |
| order timeout 후 | 실행 |

외부 개입 설정:

| 항목 | 값 |
| --- | --- |
| 외부 주문 허용 | true |
| 외부 변경 후 신규 진입 일시정지 | true |
| pause 시간 | 60초 |
| 외부 포지션 adopt | true |
| adopt된 외부 포지션 자동 관리 | false |
| 외부 open order 자동 취소 | false |

즉, Bybit 앱 등 외부에서 생긴 포지션은 대시보드 표시는 가능하지만 봇이 자동으로 TP/SL/청산 관리를 하지 않는다. 외부 변경이 감지되면 신규 진입은 60초간 멈춘다.

봇이 만든 포지션의 exchange SL/trailing stop 조건주문은 외부 주문으로 보지 않는다. 또한 봇 포지션이 Bybit 보호주문 체결로 이미 flat이 된 경우에는 `POSITION_CLOSED`로 내부 상태를 닫고, `POSITION_CLOSED_EXTERNALLY` 경고나 신규 진입 일시정지로 분류하지 않는다.

## 18. 무진입 사유 로깅

전략 신호는 있었지만 진입하지 않은 경우 `NO_ENTRY_REASON` 이벤트를 남긴다. 이 이벤트는 INFO 레벨이지만 거래 의사결정에 중요한 정보라서 이벤트 저장 필터를 통과한다.

단, 대시보드 이벤트 피드와 봇 상태의 마지막 이벤트에는 기본 노출하지 않는다. `/events?event_type=NO_ENTRY_REASON`처럼 명시 조회하거나 Daily Log 집계에서 분석용으로 사용하며, 보존정책상 일반 INFO 이벤트로 주기 정리 대상이다.

주요 필드:

- symbol
- strategy_signal_side
- signal_score
- failed_stage
- reason_code
- entry_mode_candidate
- rsi_1m / rsi_5m
- volume_ratio_1m / volume_ratio_5m
- atr_percent
- ema_gap_15m
- ema_slope_atr_15m
- distance_to_box_atr
- anti_chase_reason
- breakout_quality_reason
- retest_pending_status

대표 reason_code:

| reason_code | 의미 |
| --- | --- |
| `BREAKOUT_NOT_HEALTHY` | Breakout은 있었지만 거래량, 캔들 품질, Anti-Chase 중 하나가 부족 |
| `BREAKOUT_EXHAUSTION` | 과열 거래량으로 즉시 진입하지 않고 retest pending만 등록 |
| `SCOUT_SCORE_TOO_LOW` | Scout 조건은 일부 만족했지만 점수가 부족 |
| `SCOUT_TOO_FAR_FROM_BOX` | 박스까지 거리가 Scout 허용 ATR보다 큼 |
| `RETEST_TOO_FAR_FROM_LEVEL` | pending level과 retest 캔들의 거리가 너무 큼 |
| `PRE_ORDER_INSUFFICIENT_DEPTH` | 주문 직전 호가 깊이가 부족 |
| `RISK_REJECTED` | 리스크 한도, 레버리지, 수량 산정 조건에서 거절 |
| `COOLDOWN_ACTIVE` | cooldown 또는 kill-switch 계열 guard가 신규 진입 차단 |

Daily Log는 `NO_ENTRY_REASON`을 집계해 reason_code별, symbol별, entry_mode별, failed_stage별 count를 보여준다. 또한 가장 많이 막은 guard와 완화 후보 설정값을 함께 표시하고, 실제 체결된 거래는 entry_mode별 승률, 순손익, 평균 R로 비교한다.

## 19. 대시보드 감시종목 Preview

진입하지 않은 감시 종목은 대시보드용 preview로 발행된다.

Preview에는 아래 값이 포함된다.

- symbol
- strategy
- direction
- signal_score
- signal_reason
- readiness
- trend
- last_price
- box_high
- box_low
- distance_to_breakout_pct
- distance_atr
- atr_percent
- rsi
- volume_ratio

readiness는 실제 진입 상태가 아니라 표시용이다. 실제 주문 판단은 `EntryTimingEngine`이 담당한다.

readiness 기준:

| 상태 | 의미 |
| --- | --- |
| BREAKOUT | boundary를 margin 이상 돌파 |
| NEAR | boundary까지 0.20 ATR 이하 |
| SCOUT_ZONE | boundary까지 0.35 ATR 이하 |
| WATCHING | 아직 멀리 있음 |
| NO_SIGNAL | 전략 신호 없음 |

## 20. 현재 전략의 핵심 성격

현재 봇은 다음 성격을 가진다.

1. 종목 선정은 유동성, 변동성, 추세 잠재력, 거래량을 함께 본다.
   - USDT linear, Trading 상태, 신규상장 제외, turnover/spread/ATR 필터를 통과한 종목 중 scanner_score 상위 20개를 감시한다.

2. 방향 판단은 15m 추세와 5m 정렬에 기반한다.
   - 15m EMA20/EMA50 추세, EMA slope, EMA와 close 거리, 5m RSI/volume/ATR%를 본다.

3. 진입은 1m 가격 행동으로 세분화된다.
   - 박스 근처 compression이면 Scout.
   - 건강한 돌파면 Breakout.
   - 불건전 돌파 후 level을 지지/저항으로 확인하면 Retest.

4. 공격성은 후보군을 넓히고 진입 품질을 방어하는 쪽으로 조정되어 있다.
   - 감시종목 20개.
   - Scout min_score 6.
   - Scout distance 0.45 ATR.
   - Breakout은 IOC aggressive limit.
   - Retest tolerance 0.35 ATR.

5. 리스크는 ATR 기반 손절과 계좌 risk cap으로 제한한다.
   - 기본 account risk 1%.
   - entry mode별 fraction 적용.
   - 레버리지는 필요한 최소 정수만 쓰고 cap으로 제한한다.

6. LIVE 진입 안정성은 exchange SL 검증이 핵심이다.
   - SL이 설정/검증되지 않으면 포지션을 ACTIVE로 인정하지 않고 emergency close를 시도한다.

7. 청산은 exchange SL, 봇 관찰 기반 partial TP/trailing/stagnation/scenario invalidation, funding guard, 수동 청산이 함께 작동한다.

## 21. 설정 변경 시 영향이 큰 값

종목 선정 공격성:

- `universe.min_24h_turnover_usdt`
- `scanner.max_candidates`
- `bot.max_symbols_to_watch`
- `scanner.min_atr_percent`
- `scanner.max_atr_percent`
- `scanner.max_spread_percent`

신호 발생 빈도:

- `trend_quality.long_rsi_min_5m`
- `trend_quality.long_rsi_max_5m`
- `trend_quality.short_rsi_min_5m`
- `trend_quality.short_rsi_max_5m`
- `trend_quality.min_ema_gap_percent_15m`
- `trend_quality.min_ema20_slope_atr_15m`
- `volume.min_setup_volume_ratio`

진입 공격성:

- `entry.pre_breakout.min_score`
- `entry.pre_breakout.max_distance_to_box_atr`
- `entry.pre_breakout.min_volume_ratio`
- `entry.breakout_confirm.close_beyond_boundary_atr`
- `entry.retest_confirm.retest_tolerance_atr`
- `entry.anti_chase.*`

주문 체결 공격성:

- `orders.scout_order_type`
- `orders.breakout_order_type`
- `orders.retest_order_type`
- `orders.max_slippage_percent`
- `orders.scout_limit_order_ttl_sec`
- `orders.retest_limit_order_ttl_sec`
- `orders.limit_reorder_attempts`
- `orders.partial_fill_min_ratio_to_keep`

리스크/레버리지:

- `risk.account_risk_per_trade_percent`
- `entry.*.position_fraction`
- `risk.scout_max_leverage`
- `risk.breakout_max_leverage`
- `risk.retest_max_leverage`
- `risk.max_total_open_risk_percent`
- `risk.max_same_direction_positions`

청산/관리:

- `tpsl.initial_take_profit_r`
- `position.partial_take_profit_r`
- `position.trailing_start_r`
- `position.trailing_atr_multiplier`
- `position.max_holding_minutes`
- `stagnation_exit.*`
- `funding_guard.*`
