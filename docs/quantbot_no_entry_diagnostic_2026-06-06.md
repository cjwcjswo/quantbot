# QuantBot No-Entry Diagnostic Report

작성 시각: 2026-06-06 18:00 KST 기준  
대상 서버: live `comabot-aws`  
배포 커밋: `5e631e4`  
현재 상태: `LIVE / RUNNING`, 신규 진입 가능, kill switch 미작동, 활성 포지션 0개

## 1. 요약

현재 봇은 정상 실행 중이나, 현재 런타임에서는 체결된 거래가 없다.

현재 bot 컨테이너 시작 시각:

```text
UTC: 2026-06-06 05:21:05
KST: 2026-06-06 14:21:05
```

분석 구간:

```text
2026-06-06 14:21:05 KST ~ 2026-06-06 17:58:35 KST
약 3시간 37분
```

이 구간의 이벤트 요약:

| 항목 | 수량 | 의미 |
|---|---:|---|
| `NO_ENTRY_REASON` | 1191 | 후보가 있었지만 진입 조건 미충족 |
| `ORDER_FAILED` | 1 | 지정가 주문 미체결 |
| 실제 체결 거래 | 0 | 포지션 진입 없음 |
| 주문 시도 | 2 | `MONUSDT` Scout 지정가 주문 2회, 모두 미체결 취소 |

핵심 결론:

```text
1. 가장 큰 병목은 1분봉 거래량 비율이다.
   VOLUME_TOO_LOW가 686건, 전체 NO_ENTRY_REASON의 약 57.6%.

2. 두 번째 병목은 Scout 박스 근접 조건이다.
   SCOUT_TOO_FAR_FROM_BOX가 165건, 약 13.9%.

3. 펀딩 차단도 적지 않다.
   FUNDING_WINDOW + FUNDING_RATE_HIGH가 234건, 약 19.6%.

4. 현재 세션에서 실제 진입까지 간 사례는 없지만,
   MONUSDT는 Scout 주문까지 갔다가 지정가 미체결로 취소됐다.
```

## 2. 현재 핵심 설정

설정 원본: `config/quantbot.yaml`

### 2.1 Bot / Universe / Scanner

| 설정 | 현재 값 | 설명 |
|---|---:|---|
| `bot.mode` | `LIVE` | 실거래 모드 |
| `bot.max_active_positions` | `5` | 최대 동시 포지션 |
| `bot.max_symbols_to_watch` | `20` | 감시 종목 수 |
| `universe.min_24h_turnover_usdt` | `20,000,000` | 24h 거래대금 최소 기준 |
| `universe.exclude_new_listing_days` | `7` | 신규 상장 7일 이내 제외 |
| `scanner.refresh_interval_sec` | `180` | 감시 후보 갱신 주기 |
| `scanner.max_candidates` | `20` | 스캐너 후보 수 |
| `scanner.min_atr_percent` | `0.15` | ATR% 하한 |
| `scanner.max_atr_percent` | `7.0` | ATR% 상한 |
| `scanner.max_spread_percent` | `0.10` | 최대 스프레드 |

### 2.2 Trend Signal 조건

전략은 `trend_following` 단일 전략이다.  
15분봉으로 큰 방향을 보고, 5분봉으로 방향 정렬과 기본 거래량을 확인한다.

| 설정 | 현재 값 | 의미 |
|---|---:|---|
| `trend_quality.min_ema_gap_percent_15m` | `0.10` | 15m EMA20/EMA50 간격 최소 |
| `trend_quality.min_ema20_slope_atr_15m` | `0.03` | 15m EMA20 기울기 최소 |
| `trend_quality.min_close_distance_from_ema20_atr_15m` | `0.05` | 15m 종가가 EMA20에서 충분히 떨어져 있어야 함 |
| `trend_quality.long_rsi_min_5m` | `50` | 롱 5m RSI 하한 |
| `trend_quality.long_rsi_max_5m` | `68` | 롱 5m RSI 상한 |
| `trend_quality.short_rsi_min_5m` | `32` | 숏 5m RSI 하한 |
| `trend_quality.short_rsi_max_5m` | `50` | 숏 5m RSI 상한 |
| `volume.min_setup_volume_ratio` | `0.6` | 5m setup 거래량 비율 하한 |

롱 후보 조건 요약:

```text
15m EMA20 > EMA50
15m EMA gap >= 0.10%
15m EMA20 slope >= 0.03 ATR
15m close > EMA20 + 0.05 ATR
5m close > EMA20
5m RSI 50~68
5m volume_ratio >= 0.6
5m ATR% 0.15~7.0
```

숏 후보 조건은 위 조건의 반대 방향이다.

### 2.3 Entry 조건

현재 활성화된 진입 모드:

```yaml
entry.enabled_modes:
  pre_breakout_scout: true
  breakout_confirm: true
  retest_confirm: true
```

#### Pre-Breakout Scout

| 설정 | 현재 값 | 설명 |
|---|---:|---|
| `entry.pre_breakout.min_volume_ratio` | `0.8` | 1m 거래량 비율 하한 |
| `entry.pre_breakout.max_distance_to_box_atr` | `0.45` | 박스 경계까지 최대 거리 |
| `entry.pre_breakout.require_compression` | `false` | 압축 필수 아님 |
| `entry.pre_breakout.compression_min_score` | `6` | 압축 있을 때 필요 점수 |
| `entry.pre_breakout.no_compression_min_score` | `7` | 압축 없을 때 필요 점수 |
| `entry.pre_breakout.long_rsi_min` | `46` | 롱 1m RSI 하한 |
| `entry.pre_breakout.long_rsi_max` | `64` | 롱 1m RSI 상한 |
| `entry.pre_breakout.short_rsi_min` | `36` | 숏 1m RSI 하한 |
| `entry.pre_breakout.short_rsi_max` | `54` | 숏 1m RSI 상한 |
| `entry.pre_breakout.stop_atr` | `0.7` | Scout 기본 손절폭 |

Scout 진입 핵심:

```text
1m volume_ratio >= 0.8
박스 경계와의 거리 <= 0.45 ATR
롱 RSI 46~64 또는 숏 RSI 36~54
롱은 최근 1m 저점 상승 구조 필요
숏은 최근 1m 고점 하락 구조 필요
anti-chase 필터 통과
```

#### Breakout Confirm

| 설정 | 현재 값 | 설명 |
|---|---:|---|
| `entry.breakout_confirm.volume_min_ratio` | `1.3` | 돌파 거래량 하한 |
| `volume.max_exhaustion_volume_ratio` | `4.0` | 과열 거래량 상한 |
| `entry.breakout_confirm.stop_atr` | `1.0` | Breakout 손절폭 |
| `orders.breakout_order_type` | `AGGRESSIVE_LIMIT` | IOC aggressive limit |

#### Retest Confirm

| 설정 | 현재 값 | 설명 |
|---|---:|---|
| `entry.retest_confirm.retest_tolerance_atr` | `0.35` | 리테스트 허용 거리 |
| `entry.retest_confirm.max_wait_candles` | `10` | 리테스트 대기 캔들 수 |
| `entry.retest_confirm.stop_atr` | `1.3` | Retest 기본 손절폭 |
| `risk.retest_max_stop_distance_atr` | `1.8` | Retest 전용 최대 손절폭 |

Retest 손절폭은 ATR%에 따라 적응형으로 바뀐다.

| 1m ATR% | Retest stop ATR |
|---:|---:|
| `<= 0.25%` | `1.0` |
| `<= 0.60%` | `1.3` |
| `> 0.60%` | `1.5` |

### 2.4 Anti-Chase

| 설정 | 현재 값 | 설명 |
|---|---:|---|
| `entry.anti_chase.enabled` | `true` | 추격 진입 방지 |
| `entry.anti_chase.max_rsi_long` | `70` | 롱 RSI 과열 차단 |
| `entry.anti_chase.min_rsi_short` | `30` | 숏 RSI 과매도 차단 |
| `entry.anti_chase.max_distance_from_ema20_atr` | `1.5` | EMA20에서 너무 먼 가격 차단 |
| `entry.anti_chase.max_recent_3_candle_move_atr` | `2.0` | 최근 3개 캔들 과도한 이동 차단 |
| `entry.anti_chase.max_single_candle_move_atr` | `1.2` | 단일 캔들 급등락 차단 |
| `entry.anti_chase.exhaustion_volume_ratio` | `4.0` | 과열 거래량 차단 |

### 2.5 Orders

| 설정 | 현재 값 | 설명 |
|---|---:|---|
| `orders.live_new_entry_market_order_allowed` | `false` | 신규 진입 시장가 금지 |
| `orders.scout_order_type` | `LIMIT` | Scout는 지정가 |
| `orders.scout_limit_order_ttl_sec` | `30` | Scout 지정가 TTL |
| `orders.retest_order_type` | `LIMIT` | Retest는 지정가 |
| `orders.retest_limit_order_ttl_sec` | `20` | Retest 지정가 TTL |
| `orders.breakout_order_type` | `AGGRESSIVE_LIMIT` | Breakout은 IOC aggressive limit |
| `orders.limit_reorder_attempts` | `1` | 지정가 재시도 횟수 |

중요:

```text
LIVE 신규 진입 시장가가 꺼져 있다.
조건을 통과해도 지정가가 체결되지 않으면 포지션은 열리지 않는다.
현재 세션의 MONUSDT가 이 케이스다.
```

### 2.6 Funding Guard

| 설정 | 현재 값 | 설명 |
|---|---:|---|
| `funding_guard.enabled` | `true` | 펀딩 가드 활성화 |
| `funding_guard.block_new_entries_before_funding_min` | `10` | 펀딩 전 10분 신규 진입 금지 |
| `funding_guard.block_if_abs_funding_rate_percent_above` | `0.05` | 펀딩비 절댓값 0.05% 이상 진입 금지 |
| `funding_guard.reduce_position_if_abs_funding_rate_percent_above` | `0.10` | 0.10% 이상이면 포지션 축소 판단 |

## 3. Reason Code 설명

| Reason | 의미 | 연결 설정 |
|---|---|---|
| `VOLUME_TOO_LOW` | 1m Scout 거래량 또는 breakout 거래량 부족 | `entry.pre_breakout.min_volume_ratio=0.8`, `volume.min_breakout_volume_ratio=1.3` |
| `SCOUT_TOO_FAR_FROM_BOX` | 가격이 박스 경계에서 너무 멂 | `entry.pre_breakout.max_distance_to_box_atr=0.45` |
| `FUNDING_WINDOW` | 펀딩 시간 10분 이내 | `funding_guard.block_new_entries_before_funding_min=10` |
| `FUNDING_RATE_HIGH` | 펀딩비 절댓값이 0.05% 이상 | `funding_guard.block_if_abs_funding_rate_percent_above=0.05` |
| `PRICE_DIVERGENCE` | ticker 가격과 kline 종가 괴리 과다 | `data_quality.max_ticker_kline_price_divergence_percent=0.5` |
| `INVALID_CANDLE_OR_ATR` | 캔들 또는 ATR 계산값 불량 | candle/indicator data |
| `ANTI_CHASE_LONG` | 롱 추격 진입 차단 | RSI 과열, EMA20 이격, 급등 캔들, 약한 종가 위치 등 |
| `TREND_CONDITION_FAILED` | Scout 1m RSI 등 세부 방향 조건 실패 | `entry.pre_breakout.long/short_rsi_*` |
| `SCOUT_STRUCTURE_WEAK` | Scout 구조 부족 | 롱: 최근 저점 상승 부족, 숏: 최근 고점 하락 부족 |
| `BREAKOUT_EXHAUSTION` | 돌파 거래량이 과열권 | `volume.max_exhaustion_volume_ratio=4.0` |

## 4. 현재 세션 NO_ENTRY 집계

### 4.1 전체 Reason 분포

| Reason | Count | 비율 |
|---|---:|---:|
| `VOLUME_TOO_LOW` | 686 | 57.6% |
| `SCOUT_TOO_FAR_FROM_BOX` | 165 | 13.9% |
| `FUNDING_WINDOW` | 148 | 12.4% |
| `FUNDING_RATE_HIGH` | 86 | 7.2% |
| `PRICE_DIVERGENCE` | 51 | 4.3% |
| `INVALID_CANDLE_OR_ATR` | 19 | 1.6% |
| `ANTI_CHASE_LONG` | 13 | 1.1% |
| `TREND_CONDITION_FAILED` | 11 | 0.9% |
| `SCOUT_STRUCTURE_WEAK` | 9 | 0.8% |
| `BREAKOUT_EXHAUSTION` | 3 | 0.3% |

### 4.2 실패 단계

| Stage | Count | 비율 | 의미 |
|---|---:|---:|---|
| `entry_timing` | 906 | 76.1% | 큰 방향 후보는 있었으나 마지막 진입 타이밍 실패 |
| `pre_gate` | 285 | 23.9% | 펀딩, 데이터 품질 등 사전 차단 |

### 4.3 Reason별 평균 수치

| Reason | N | 평균 1m vol | 중앙 1m vol | 평균 dist ATR | 중앙 dist ATR | 평균 RSI 1m | 평균 RSI 5m |
|---|---:|---:|---:|---:|---:|---:|---:|
| `VOLUME_TOO_LOW` | 686 | 0.295 | 0.250 | 2.099 | 1.936 | 53.22 | 57.15 |
| `SCOUT_TOO_FAR_FROM_BOX` | 165 | 1.495 | 1.263 | 1.720 | 1.542 | 55.46 | 56.61 |
| `FUNDING_WINDOW` | 148 | 0.686 | 0.339 | 1.346 | 1.085 | 57.02 | 54.05 |
| `FUNDING_RATE_HIGH` | 86 | 0.625 | 0.396 | 2.142 | 1.383 | 43.21 | 47.23 |
| `PRICE_DIVERGENCE` | 51 | 0.775 | 0.626 | 1.948 | 1.683 | 53.13 | 54.59 |
| `ANTI_CHASE_LONG` | 13 | 1.411 | 1.334 | 0.334 | 0.292 | 61.80 | 61.84 |
| `TREND_CONDITION_FAILED` | 11 | 1.526 | 1.568 | 0.217 | 0.191 | 62.83 | 59.15 |
| `SCOUT_STRUCTURE_WEAK` | 9 | 2.217 | 2.194 | 0.265 | 0.244 | 66.23 | 58.37 |

해석:

```text
VOLUME_TOO_LOW는 평균 1m volume_ratio가 0.295다.
현재 Scout 기준 0.8과 차이가 크다.

SCOUT_TOO_FAR_FROM_BOX는 평균 distance_to_box_atr가 1.72다.
현재 Scout 기준 0.45 ATR보다 훨씬 멀다.

ANTI_CHASE_LONG / TREND_CONDITION_FAILED / SCOUT_STRUCTURE_WEAK는
거래량과 거리 조건은 맞았지만 RSI 과열, EMA 이격, 캔들 구조가 문제였던 근접 실패 케이스다.
```

## 5. 종목별 주요 차단 사유

현재 세션에서 로그가 나온 종목 기준이다.

| Symbol | 주요 Reason | Count 요약 | 최신 차단 수치 |
|---|---|---:|---|
| `LABUSDT` | `VOLUME_TOO_LOW`, `FUNDING_RATE_HIGH`, `FUNDING_WINDOW` | 205 | 최신 `FUNDING_WINDOW`, short score 9, vol1m 0.298, dist 1.475 |
| `BEATUSDT` | `VOLUME_TOO_LOW`, `SCOUT_TOO_FAR_FROM_BOX`, `ANTI_CHASE_LONG` | 182 | 최신 `VOLUME_TOO_LOW`, long score 9, vol1m 0.114, dist 1.577 |
| `ALLOUSDT` | `VOLUME_TOO_LOW`, `FUNDING_WINDOW`, `PRICE_DIVERGENCE` | 145 | 최신 `PRICE_DIVERGENCE`, long score 9, vol1m 0.742, dist 0.961 |
| `LITUSDT` | `VOLUME_TOO_LOW`, `FUNDING_WINDOW`, `SCOUT_TOO_FAR_FROM_BOX` | 128 | 최신 `VOLUME_TOO_LOW`, long score 9, vol1m 0.192, dist 4.186 |
| `INJUSDT` | `VOLUME_TOO_LOW`, `FUNDING_WINDOW`, `SCOUT_TOO_FAR_FROM_BOX` | 108 | 최신 `SCOUT_TOO_FAR_FROM_BOX`, long score 9, vol1m 0.937, dist 0.792 |
| `OPNUSDT` | `VOLUME_TOO_LOW`, `SCOUT_TOO_FAR_FROM_BOX` | 101 | 최신 `SCOUT_TOO_FAR_FROM_BOX`, long score 9, vol1m 0.961, dist 3.686 |
| `ENAUSDT` | `VOLUME_TOO_LOW`, `SCOUT_TOO_FAR_FROM_BOX`, `SCOUT_STRUCTURE_WEAK` | 72 | 최신 `VOLUME_TOO_LOW`, long score 8, vol1m 0.701, dist 1.124 |
| `MONUSDT` | `VOLUME_TOO_LOW`, `SCOUT_TOO_FAR_FROM_BOX`, `SCOUT_STRUCTURE_WEAK` | 60 | 최신 `VOLUME_TOO_LOW`, long score 9, vol1m 0.516, dist 2.613 |
| `MUUSDT` | `VOLUME_TOO_LOW`, `FUNDING_WINDOW` | 49 | 최신 `VOLUME_TOO_LOW`, short score 9, vol1m 0.668, dist 1.834 |
| `BABYUSDT` | `VOLUME_TOO_LOW`, `SCOUT_TOO_FAR_FROM_BOX` | 43 | 최신 `SCOUT_TOO_FAR_FROM_BOX`, short score 9, vol1m 3.072, dist 3.630 |
| `HOMEUSDT` | `FUNDING_RATE_HIGH`, `PRICE_DIVERGENCE` | 37 | 최신 `FUNDING_RATE_HIGH`, long score 10, vol1m 2.452, dist 5.372 |
| `HYPEUSDT` | `VOLUME_TOO_LOW`, `SCOUT_TOO_FAR_FROM_BOX` | 28 | 최신 `SCOUT_TOO_FAR_FROM_BOX`, long score 8, vol1m 1.041, dist 2.166 |
| `BCHUSDT` | `SCOUT_TOO_FAR_FROM_BOX`, `VOLUME_TOO_LOW` | 10 | 최신 `VOLUME_TOO_LOW`, long score 9, vol1m 0.238, dist 2.918 |
| `NEARUSDT` | `VOLUME_TOO_LOW`, `INVALID_CANDLE_OR_ATR` | 10 | 최신 `VOLUME_TOO_LOW`, short score 9, vol1m 0.371, dist 2.674 |
| `BNBUSDT` | `VOLUME_TOO_LOW` | 9 | 최신 `VOLUME_TOO_LOW`, long score 8, vol1m 0.144, dist 3.802 |
| `RENDERUSDT` | `VOLUME_TOO_LOW` | 1 | latest short score 8, vol1m 0.356, dist 0.396 |

## 6. 거의 진입할 뻔한 케이스

아래는 `volume_ratio_1m >= 0.8`이고 `distance_to_box_atr <= 0.45`였는데도 막힌 사례다.  
즉, 단순히 거래량/거리만 완화한다고 전부 진입되는 케이스는 아니다.

| KST | Symbol | Side | Score | Reason | vol1m | dist ATR | RSI 1m | RSI 5m | 세부 이유 |
|---|---|---|---:|---|---:|---:|---:|---:|---|
| 17:40 | `BEATUSDT` | LONG | 10 | `TREND_CONDITION_FAILED` | 2.264 | 0.416 | 82.03 | 65.15 | Scout 롱 RSI 상한 64 초과 |
| 17:40 | `BEATUSDT` | LONG | 10 | `PRICE_DIVERGENCE` | 2.264 | 0.416 | 82.03 | 65.15 | 가격 데이터 괴리 차단 |
| 17:38 | `ENAUSDT` | LONG | 8 | `TREND_CONDITION_FAILED` | 1.756 | 0.220 | 65.97 | 56.33 | Scout 롱 RSI 상한 64 초과 |
| 17:32 | `ENAUSDT` | LONG | 8 | `SCOUT_STRUCTURE_WEAK` | 2.194 | 0.425 | 61.14 | 53.12 | 최근 저점 상승 구조 부족 |
| 17:30 | `INJUSDT` | LONG | 9 | `ANTI_CHASE_LONG` | 1.233 | 0.370 | 63.39 | 58.29 | `PRICE_FAR_ABOVE_EMA` |
| 17:20 | `MONUSDT` | LONG | 9 | `TREND_CONDITION_FAILED` | 1.568 | 0.191 | 77.50 | 63.06 | Scout 롱 RSI 상한 64 초과 |
| 17:17 | `MONUSDT` | LONG | 8 | `SCOUT_STRUCTURE_WEAK` | 3.406 | 0.244 | 65.25 | 61.00 | 구조 부족, RSI도 상한 초과 근처 |
| 17:15 | `LABUSDT` | SHORT | 9 | `FUNDING_RATE_HIGH` | 0.983 | 0.119 | 26.44 | 33.58 | 펀딩비 차단 |
| 16:58 | `ALLOUSDT` | LONG | 10 | `FUNDING_WINDOW` | 5.914 | 0.254 | 82.72 | 65.62 | 펀딩 직전 차단, RSI 과열 |
| 16:56 | `ALLOUSDT` | LONG | 9 | `PRICE_DIVERGENCE` | 3.491 | 0.409 | 76.51 | 63.41 | 가격 데이터 괴리, RSI 과열 |

## 7. 주문 시도 및 실패

현재 세션에서는 `MONUSDT`에 Scout 지정가 주문이 2번 나갔다.

| KST | Symbol | Side | Type | Qty | Price | Status | Entry Mode | Fill |
|---|---|---|---|---:|---:|---|---|---|
| 17:11:22 | `MONUSDT` | Buy | LIMIT | 13405 | 0.020936 | CANCELLED | `PRE_BREAKOUT_SCOUT` | 0 |
| 17:11:53 | `MONUSDT` | Buy | LIMIT | 13405 | 0.020936 | CANCELLED | `PRE_BREAKOUT_SCOUT` | 0 |

관련 이벤트:

```text
2026-06-06 17:11:53 KST
ORDER_FAILED / MONUSDT / LIMIT_UNFILLED
```

해석:

```text
조건을 통과한 케이스가 아예 없었던 것은 아니다.
하지만 LIVE 신규 시장가 진입이 꺼져 있고 Scout는 지정가 주문이므로,
가격이 지정가까지 오지 않으면 포지션이 열리지 않는다.
```

## 8. 현재 감시종목 스냅샷

Redis `bot:watchlist` 기준, 2026-06-06 17:57 KST 부근 스냅샷이다.  
스냅샷은 실시간으로 바뀌며, `NO_SIGNAL`은 아직 trend_following 전략 후보가 아니라는 뜻이다.

| Symbol | Readiness | Trend | Direction | Score | ATR% | RSI | 1m vol | 비고 |
|---|---|---|---|---:|---:|---:|---:|---|
| `BTCUSDT` | `NO_SIGNAL` | UP | NONE | - | 0.087 | 54.27 | 0.588 | 5m/15m 조건 미충족 |
| `ETHUSDT` | `NO_SIGNAL` | DOWN | NONE | - | 0.137 | 47.70 | 0.234 | 5m/15m 조건 미충족 |
| `BEATUSDT` | `NO_SIGNAL` | UP | NONE | - | 0.621 | 69.37 | 0.271 | RSI 높고 현재 거래량 약함 |
| `HYPEUSDT` | `WATCHING` | UP | LONG | 8 | 0.256 | 46.78 | 0.569 | 후보지만 Scout vol 0.8 미달, dist 1.578 |
| `ENAUSDT` | `NO_SIGNAL` | UP | NONE | - | 0.409 | 45.80 | 0.561 | RSI/거래량 애매 |
| `BNBUSDT` | `NO_SIGNAL` | UP | NONE | - | 0.106 | 52.04 | 0.082 | 변동성/거래량 낮음 |
| `OPNUSDT` | `NO_SIGNAL` | UP | NONE | - | 0.875 | 22.32 | 3.388 | RSI가 롱 후보와 반대 |
| `BCHUSDT` | `NO_SIGNAL` | UP | NONE | - | 0.194 | 40.34 | 0.694 | RSI/거래량 애매 |
| `INJUSDT` | `NO_SIGNAL` | UP | NONE | - | 0.385 | 55.50 | 0.418 | 거래량 낮음 |
| `LITUSDT` | `NO_SIGNAL` | UP | NONE | - | 0.355 | 43.57 | 0.823 | 거래량은 근접, 방향 조건 미충족 |
| `MONUSDT` | `NO_SIGNAL` | UP | NONE | - | 0.192 | 60.44 | 0.713 | Scout vol 0.8에 살짝 미달 |
| `HUSDT` | `NO_SIGNAL` | UP | NONE | - | 0.213 | 47.86 | 0.219 | 거래량 낮음 |
| `ALLOUSDT` | `NO_SIGNAL` | UP | NONE | - | 1.160 | 68.11 | 0.741 | RSI 상단/거래량 미달 |
| `HOMEUSDT` | `NO_SIGNAL` | DOWN | NONE | - | 2.792 | 21.45 | 0.558 | RSI 과매도/펀딩 이슈 |
| `LABUSDT` | `NO_SIGNAL` | DOWN | NONE | - | 0.685 | 48.59 | 0.514 | 펀딩 이슈 빈번 |
| `CLOUSDT` | `NO_SIGNAL` | UP | NONE | - | 0.902 | 35.45 | 0.664 | RSI가 롱 후보와 반대 |
| `DOGEUSDT` | `NO_SIGNAL` | DOWN | NONE | - | 0.160 | 58.66 | 1.278 | 숏 RSI 범위 이탈 |
| `NEARUSDT` | `NO_SIGNAL` | DOWN | NONE | - | 0.317 | 54.65 | 1.599 | 숏 RSI 범위 이탈 |
| `1000PEPEUSDT` | `NO_SIGNAL` | DOWN | NONE | - | 0.198 | 57.18 | 1.700 | 숏 RSI 범위 이탈 |
| `AVAXUSDT` | `NO_SIGNAL` | DOWN | NONE | - | 0.190 | 58.08 | 0.614 | 숏 RSI 범위 이탈 |

## 9. 외부 조언 요청 시 핵심 질문

아래 포인트를 중심으로 조언을 받으면 좋다.

```text
1. 현재 Scout 1m volume_ratio 기준 0.8이 너무 높은가?
   - 현재 VOLUME_TOO_LOW 평균 vol1m = 0.295, 중앙값 = 0.250.
   - 근접 후보 중 0.6~0.8 사이에서 많이 잘리는지 확인 필요.

2. max_distance_to_box_atr 0.45가 너무 빡센가?
   - SCOUT_TOO_FAR_FROM_BOX 평균 dist = 1.72 ATR, 중앙값 = 1.54 ATR.
   - 다만 이 값을 크게 풀면 박스 근처가 아니라 이미 많이 움직인 자리도 잡을 수 있음.

3. 펀딩 가드가 너무 많은 기회를 막고 있는가?
   - FUNDING_WINDOW + FUNDING_RATE_HIGH = 234건, 전체의 19.6%.
   - HOME, LAB, ALLO, INJ 등에서 영향이 큼.

4. LIVE 신규 시장가 진입 금지 정책이 기회 손실을 만드는가?
   - MONUSDT는 조건 통과 후 지정가 미체결로 실패.
   - Scout 지정가 TTL 30초, 재시도 1회.

5. 1m RSI 범위가 너무 좁은가?
   - Scout 롱 RSI 46~64.
   - BEAT, ENA, MON은 거래량/거리 조건을 통과하고도 RSI 65~82에서 막힌 사례가 있음.

6. PRICE_DIVERGENCE 차단이 적절한가?
   - 현재 51건.
   - 급변동 코인에서 ticker와 kline close 괴리가 자주 발생할 수 있음.
```

## 10. 한 줄 결론

현재 거래가 없는 주된 이유는 봇 장애가 아니라, `Scout 1m 거래량 0.8`, `박스 근접 0.45 ATR`, `펀딩 가드`, `추격 진입 방지`가 동시에 작동하면서 대부분의 후보를 걸러내고 있기 때문이다.  
특히 현재 세션에서는 거래량 부족이 압도적인 1순위 병목이고, 실제 주문까지 간 `MONUSDT`는 지정가 미체결로 포지션이 열리지 않았다.
