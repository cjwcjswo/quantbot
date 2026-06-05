# QuantBot Backend API 구현 문서 v1.1
## FastAPI 기반 관제 서버 개발 프롬프트

## 1. 문서 목적

이 문서는 AI 개발 에이전트가 QuantBot의 Backend API를 실제로 구현할 수 있도록 작성된 개발 명세다.

Backend API의 목적은 다음과 같다.

```text
Frontend Dashboard와 Bot Engine 사이의 관제 계층을 제공한다.
Bot Engine 상태, 포지션, 주문, 거래 기록, 리스크 상태를 조회한다.
사용자 명령을 검증하고 Redis Command Queue로 전달한다.
Bot Engine이 publish한 Redis 실시간 상태를 Frontend에 WebSocket으로 전달한다.
PostgreSQL에 저장된 영구 데이터를 조회한다.
전략 설정을 조회/수정한다.
```

Backend API는 다음을 절대 수행하지 않는다.

```text
Bybit API 직접 호출
직접 주문 실행
전략 신호 생성
포지션 직접 관리
손절/익절 직접 판단
TP/SL 직접 설정
Bot Engine 내부 루프 실행
```

---

# 2. 기술 스택

권장 스택:

```text
Python 3.11+
FastAPI
Pydantic v2
SQLAlchemy 2.x
Alembic
PostgreSQL
Redis
asyncpg
redis-py asyncio
Uvicorn
pytest
ruff
mypy
```

선택 원칙:

```text
Bot Engine과 Python 모델을 공유하기 쉽다.
Pydantic 기반 요청/응답 검증이 명확하다.
비동기 WebSocket/Redis 처리에 적합하다.
```

---

# 3. Backend API의 책임 범위

## 3.1 수행하는 것

```text
REST API 제공
WebSocket API 제공
PostgreSQL 데이터 조회
Redis 실시간 상태 조회
Redis Command Queue 발행
command_log 저장
strategy_config 조회/수정
bot status 조회
PAPER/LIVE 모드 조회
manual intervention 이벤트 조회
TP/SL 보호 상태 조회
reconciliation 상태 조회
```

## 3.2 수행하지 않는 것

```text
Bybit 주문
Bybit 포지션 조회
Bybit TP/SL 설정
시장 데이터 직접 수집
전략 판단
RiskManager 역할
OrderManager 역할
PositionManager 역할
```

---

# 4. 전체 Backend 구조

권장 폴더 구조:

```text
apps/
  api/
    main.py
    lifespan.py
    dependencies.py

    routers/
      health.py
      bot.py
      positions.py
      orders.py
      trades.py
      pnl.py
      strategy_config.py
      events.py
      settings.py
      websocket.py

    schemas/
      common.py
      bot.py
      positions.py
      orders.py
      trades.py
      pnl.py
      strategy_config.py
      events.py
      commands.py

    services/
      bot_status_service.py
      command_service.py
      position_service.py
      order_service.py
      trade_service.py
      pnl_service.py
      strategy_config_service.py
      event_service.py
      realtime_service.py

    repositories/
      position_repository.py
      order_repository.py
      trade_repository.py
      signal_repository.py
      event_repository.py
      config_repository.py
      command_repository.py

    websocket/
      connection_manager.py
      dashboard_stream.py

packages/
  core/
    models/
    enums/
    errors/

  storage/
    database.py
    models.py

  messaging/
    redis_client.py
    command_queue.py
    event_bus.py

  config/
    settings.py
```

---

# 5. 실행 구조

Backend API는 Bot Engine과 별도 프로세스로 실행한다.

```bash
python -m apps.api.run
```

`apps.api.run`은 `config/quantbot.yaml`의 `api.api_host`, `api.api_port`를 읽어
Uvicorn을 실행한다.

Docker Compose 기준:

```yaml
services:
  api:
    build: .
    command: python -m apps.api.run
    depends_on:
      - postgres
      - redis

  bot:
    build: .
    command: python -m apps.bot.main
    depends_on:
      - postgres
      - redis
```

Backend API는 Bot Engine을 직접 import해서 실행하면 안 된다.

---

# 6. 환경 변수 / YAML 설정

Backend API의 비밀값과 인프라 연결 정보는 `.env`, 일반 런타임 설정은
`config/quantbot.yaml`의 `api` 섹션에서 관리한다.

`.env` 예시:

```env
DATABASE_URL=postgresql+asyncpg://quantbot:quantbot@postgres:5432/quantbot
REDIS_URL=redis://redis:6379/0
QUANTBOT_CONFIG=config/quantbot.yaml

API_TOKEN_DEV=dev-token
```

`config/quantbot.yaml` 예시:

```yaml
api:
  app_env: "local"
  api_host: "0.0.0.0"
  api_port: 8000
  cors_origins:
    - "http://localhost:5173"
    - "http://127.0.0.1:5173"
  api_auth_enabled: false
  heartbeat_alive_sec: 15
  api_run_maintenance: true
```

Redis key 이름은 코드의 `packages.messaging.state_keys` 및 command queue 기본값을
사용한다.


---

# 7. API 인증 정책

v1.0에서는 로컬/개인용 대시보드를 우선한다.

```yaml
auth:
  enabled: false
  dev_token_enabled: true
```

단, 구조는 인증 추가를 고려해 둔다.

요청 헤더:

```http
Authorization: Bearer <token>
```

인증 활성화 시 보호 대상:

```text
POST /bot/start
POST /bot/stop
POST /bot/pause
POST /bot/resume
POST /positions/{symbol}/close
POST /orders/{order_id}/cancel
PUT /strategy/config
POST /bot/sync
```

조회 API는 추후 설정에 따라 보호 가능해야 한다.

---

# 8. 공통 응답 포맷

성공 응답:

```json
{
  "ok": true,
  "data": {},
  "error": null
}
```

실패 응답:

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "BOT_NOT_RUNNING",
    "message": "Bot is not running.",
    "details": {}
  }
}
```

공통 에러 코드:

```text
VALIDATION_ERROR
NOT_FOUND
BOT_NOT_RUNNING
BOT_COMMAND_REJECTED
COMMAND_QUEUE_UNAVAILABLE
DATABASE_ERROR
REDIS_ERROR
UNAUTHORIZED
FORBIDDEN
CONFLICT
INTERNAL_ERROR
```

---

# 9. Bot 상태 API

## 9.1 GET /health

목적:

```text
Backend API 자체 상태 확인
```

응답:

```json
{
  "ok": true,
  "data": {
    "status": "OK",
    "api": "UP",
    "postgres": "UP",
    "redis": "UP",
    "timestamp": "2026-06-04T09:00:00Z"
  },
  "error": null
}
```

## 9.2 GET /bot/status

목적:

```text
Bot Engine의 현재 상태 조회
```

데이터 소스:

```text
Redis:
bot:status
bot:mode
bot:heartbeat
bot:risk_status
bot:protection_status
bot:reconciliation_status

PostgreSQL:
최근 bot_events
```

응답 필드:

```json
{
  "state": "STANDBY",
  "mode": "PAPER",
  "heartbeat_at": "2026-06-04T09:00:00Z",
  "is_alive": true,
  "is_trading_enabled": false,
  "risk_status": "NORMAL",
  "protection_status": "OK",
  "reconciliation_status": "OK",
  "last_event": {
    "event_type": "BOT_STANDBY",
    "message": "Bot is waiting for START command."
  }
}
```

`is_alive` 판단:

```text
현재 서버 시간 - heartbeat_at <= 15초 → true
15초 초과 → false
```

---

# 10. Bot 명령 API

Backend API는 명령을 직접 실행하지 않는다.  
명령을 검증하고 PostgreSQL `command_logs`에 저장한 뒤 Redis Command Queue에 발행한다.

공통 명령 객체:

```json
{
  "command_id": "uuid",
  "type": "START_BOT",
  "requested_by": "dashboard",
  "requested_at": "2026-06-04T09:00:00Z",
  "payload": {},
  "status": "PENDING"
}
```

## 10.1 POST /bot/start

목적:

```text
Bot Engine을 STANDBY에서 RUNNING으로 전환 요청
```

요청:

```json
{}
```

실행 mode:

```text
config/quantbot.yaml의 bot.mode 사용
```

검증:

```text
현재 Bot 상태가 STANDBY / PAUSED / STOPPED 중 하나인지 확인
이미 RUNNING이면 409 CONFLICT 반환
현재 설정 mode가 LIVE이면 live_confirm=true 필요
```

LIVE 요청:

```json
{
  "live_confirm": true
}
```

LIVE 시작 조건:

```text
live_confirm == true
config/quantbot.yaml의 api.api_auth_enabled == true 권장
최근 heartbeat 정상
Bot Engine이 STANDBY 또는 PAUSED
```

Redis 명령:

```json
{
  "type": "START_BOT",
  "payload": {}
}
```

---

## 10.2 POST /bot/stop

목적:

```text
Bot Engine 정지 요청
```

요청:

```json
{
  "close_positions": false,
  "cancel_open_orders": true
}
```

정책:

```text
close_positions=false 기본값
cancel_open_orders=true 기본값
실제 포지션 청산은 Bot Engine이 결정/실행
Backend는 명령만 전달
```

---

## 10.3 POST /bot/pause

목적:

```text
신규 진입 중지
```

요청:

```json
{
  "reason": "manual pause"
}
```

의미:

```text
신규 진입 중지
기존 봇 관리 포지션은 계속 관리 가능
```

---

## 10.4 POST /bot/resume

목적:

```text
PAUSED 상태에서 거래 재개 요청
```

검증:

```text
현재 상태가 PAUSED인지 확인
RISK_LOCKED 또는 EMERGENCY_STOP이면 resume 금지
```

---

## 10.5 POST /bot/sync

목적:

```text
즉시 Bybit 상태 동기화 요청
```

Redis 명령:

```json
{
  "type": "SYNC_NOW",
  "payload": {}
}
```

---

# 11. Position API

## 11.1 GET /positions

목적:

```text
현재 포지션 목록 조회
```

데이터 우선순위:

```text
1. Redis bot:positions 실시간 스냅샷
2. Redis에 없으면 PostgreSQL positions의 open 상태 조회
```

응답 예시:

```json
{
  "positions": [
    {
      "symbol": "BTCUSDT",
      "side": "LONG",
      "source": "BOT",
      "mode": "LIVE",
      "qty": "0.010",
      "manual_added_qty": "0.002",
      "avg_entry_price": "65000.0",
      "mark_price": "65300.0",
      "unrealized_pnl": "3.00",
      "unrealized_pnl_percent": "0.46",
      "leverage": "3",
      "entry_mode": "RETEST_CONFIRM",
      "strategy_id": "trend_following",
      "protection_status": "TPSL_OK",
      "stop_loss_price": "64000.0",
      "take_profit_price": "67000.0",
      "opened_at": "2026-06-04T09:00:00Z"
    }
  ]
}
```

필수 필드:

```text
symbol
side
source
mode
qty
manual_added_qty
avg_entry_price
mark_price
unrealized_pnl
leverage
entry_mode
strategy_id
protection_status
stop_loss_price
take_profit_price
opened_at
```

source 허용값:

```text
BOT
EXTERNAL
MANUAL_ADDED
```

---

## 11.2 GET /positions/{symbol}

목적:

```text
특정 심볼 포지션 상세 조회
```

포함 정보:

```text
현재 포지션
포지션 이벤트
진입 신호
주문/체결 이력
TP/SL 보호 상태
수동 개입 이력
reconciliation 이력
```

---

## 11.3 POST /positions/{symbol}/close

목적:

```text
특정 포지션 수동 청산 요청
```

요청:

```json
{
  "close_percent": 100,
  "reason": "manual dashboard close"
}
```

검증:

```text
close_percent > 0 and close_percent <= 100
포지션 존재 여부 확인
Bot 상태가 EMERGENCY_STOP이 아니어도 close 명령은 허용
```

Redis 명령:

```json
{
  "type": "CLOSE_POSITION",
  "payload": {
    "symbol": "BTCUSDT",
    "close_percent": 100,
    "reason": "manual dashboard close"
  }
}
```

Backend는 직접 청산 주문을 넣지 않는다.

---

# 12. Orders API

## 12.1 GET /orders

Query parameters:

```text
symbol
status
source
mode
limit
offset
from
to
```

status 허용값:

```text
NEW
PARTIALLY_FILLED
FILLED
CANCELED
REJECTED
EXPIRED
FAILED
UNKNOWN
```

source 허용값:

```text
BOT
EXTERNAL
PAPER
```

---

## 12.2 POST /orders/{order_id}/cancel

목적:

```text
미체결 주문 취소 요청
```

Backend는 직접 주문 취소 API를 호출하지 않는다.

Redis 명령:

```json
{
  "type": "CANCEL_ORDER",
  "payload": {
    "order_id": "abc",
    "reason": "manual dashboard cancel"
  }
}
```

---

# 13. Trades / Fills API

## 13.1 GET /trades

목적:

```text
거래 내역 조회
```

필터:

```text
symbol
strategy_id
entry_mode
mode
from
to
limit
offset
```

## 13.2 GET /fills

목적:

```text
체결 내역 조회
```

필터:

```text
symbol
order_id
mode
from
to
limit
offset
```

---

# 14. PnL API

## 14.1 GET /pnl/summary

응답:

```json
{
  "mode": "PAPER",
  "equity": "10050.00",
  "daily_net_pnl": "50.00",
  "daily_net_pnl_percent": "0.50",
  "realized_pnl": "30.00",
  "unrealized_pnl": "20.00",
  "fees": "2.00",
  "funding_fees": "0.00",
  "max_drawdown_today": "1.20",
  "updated_at": "2026-06-04T09:00:00Z"
}
```

daily_net_pnl 기준:

```text
realized_pnl + unrealized_pnl - fees - funding_fees
```

## 14.2 GET /pnl/daily

목적:

```text
일별 손익 조회
```

---

# 15. Strategy Config API

## 15.1 GET /strategy/config

목적:

```text
현재 전략 설정 조회
```

응답:

```json
{
  "config_version": 12,
  "mode": "PAPER",
  "strategy": {
    "active_strategies": ["trend_following"]
  },
  "risk": {},
  "entry": {},
  "orders": {}
}
```

## 15.2 PUT /strategy/config

목적:

```text
전략 설정 변경 요청
```

중요:

```text
Backend는 schema validation만 수행한다.
실제 적용은 Bot Engine이 RELOAD_CONFIG 명령을 수신한 뒤 수행한다.
open position이 있을 때 risk/leverage/stop_loss 관련 설정 변경은 기본적으로 금지한다.
```

요청:

```json
{
  "config_version": 12,
  "patch": {
    "risk": {
      "account_risk_per_trade_percent": 0.8
    }
  },
  "reason": "reduce risk"
}
```

검증:

```text
config_version 일치 확인
patch schema validation
허용되지 않는 필드 변경 차단
config_version 증가
strategy_configs 저장
RELOAD_CONFIG 명령 발행
```

---

# 16. Events API

## 16.1 GET /events

목적:

```text
Bot 이벤트 조회
```

필터:

```text
event_type
severity
symbol
from
to
limit
offset
```

event_type 예시:

```text
BOT_STANDBY
BOT_STARTED
BOT_PAUSED
BOT_STOPPED
RISK_LOCKED
ORDER_LOCKED
EMERGENCY_STOP
SIGNAL_CREATED
ORDER_CREATED
ORDER_FILLED
POSITION_OPENED
POSITION_CLOSED
TPSL_SET
TPSL_VERIFIED
TPSL_FAILED
RECONCILIATION_STARTED
RECONCILIATION_COMPLETED
MANUAL_INTERVENTION_DETECTED
MANUAL_QTY_INCREASED
MANUAL_QTY_DECREASED
EXTERNAL_ORDER_DETECTED
```

severity:

```text
INFO
WARNING
ERROR
CRITICAL
```

---

# 17. WebSocket API

## 17.1 WS /ws/dashboard

목적:

```text
Dashboard에 실시간 상태 제공
```

Backend는 Redis 상태와 events:bot pub/sub을 구독하여 Frontend에 전달한다.

전송 이벤트 타입:

```text
bot_status
pnl_update
position_update
order_update
trade_update
risk_update
protection_update
reconciliation_update
manual_intervention_event
bot_event
```

메시지 포맷:

```json
{
  "type": "position_update",
  "timestamp": "2026-06-04T09:00:00Z",
  "data": {}
}
```

전송 주기:

```text
상태 변경 이벤트: 즉시
PnL 업데이트: 최대 1초에 1회 throttle
heartbeat: 5초에 1회
```

연결 정책:

```text
클라이언트 연결 시 최신 snapshot 즉시 전송
이후 변경 이벤트 push
연결 종료 시 connection cleanup
```

---

# 18. PostgreSQL 읽기 모델

Backend API는 다음 테이블 또는 view를 조회한다고 가정한다.

```text
positions
orders
fills
trades
signals
bot_events
command_logs
strategy_configs
daily_pnl
reconciliation_logs
manual_intervention_logs
position_protection_logs
paper_account_snapshots
```

Backend는 복잡한 계산을 과도하게 수행하지 않는다.  
가능하면 Bot Engine이 저장한 결과와 스냅샷을 조회한다.

---

# 19. Redis 읽기 모델

Backend API가 읽는 Redis key:

```text
bot:status
bot:mode
bot:heartbeat
bot:risk_status
bot:positions
bot:pnl
bot:protection_status
bot:reconciliation_status
bot:latest_events
```

Backend API가 쓰는 Redis key/channel:

```text
commands:bot
```

Backend API가 구독하는 Redis channel:

```text
events:bot
```

---

# 20. Command 처리 정책

명령 생성 시 반드시 다음을 수행한다.

```text
command_id 생성
요청 schema validation
현재 bot status 검증
command_logs에 PENDING 저장
Redis commands:bot에 publish
응답으로 command_id 반환
```

명령 응답:

```json
{
  "command_id": "uuid",
  "status": "PENDING"
}
```

Bot Engine이 명령 처리 결과를 저장하면 Backend는 command_logs에서 상태를 조회할 수 있어야 한다.

command status:

```text
PENDING
ACCEPTED
REJECTED
COMPLETED
FAILED
EXPIRED
```

---

# 21. 에러 처리 정책

## 21.1 Redis 장애

Redis 장애 시:

```text
조회 API 중 Redis 기반 실시간 상태는 degraded로 응답
명령 API는 503 반환
WebSocket은 degraded 이벤트 전송 후 재시도
```

## 21.2 PostgreSQL 장애

PostgreSQL 장애 시:

```text
기록 조회 API는 503 반환
명령 API는 command_log 저장 불가 시 명령 발행 금지
```

명령 로그 없이 Redis에 명령을 발행하면 안 된다.

## 21.3 Bot Heartbeat 끊김

heartbeat가 15초 이상 갱신되지 않으면:

```text
is_alive=false
bot_status=UNKNOWN 또는 DISCONNECTED로 표시
명령 API는 START/STOP/SYNC만 제한적으로 허용
포지션 청산 요청은 위험하므로 Bot 비활성 상태에서는 거절
```

---

# 22. 보안 / 안전 정책

v1.0 로컬 개발에서는 인증을 비활성화할 수 있다.

운영 환경에서는 다음을 권장한다.

```text
API 인증 활성화
CORS origin 제한
LIVE 시작 시 추가 확인
명령 API rate limit
감사 로그 저장
```

위험 명령:

```text
START_BOT with LIVE
CLOSE_POSITION
CANCEL_ORDER
PUT /strategy/config
STOP_BOT with close_positions=true
```

위험 명령은 command_log에 반드시 저장한다.

---

# 23. 테스트 체크리스트

## Phase 1. API 기본

- [ ] FastAPI 앱 실행
- [ ] health check
- [ ] DB 연결 확인
- [ ] Redis 연결 확인
- [ ] 공통 응답 포맷 테스트
- [ ] 공통 에러 포맷 테스트

## Phase 2. Bot Status

- [ ] Redis bot:status 조회
- [ ] heartbeat 15초 기준 is_alive 계산
- [ ] bot mode 조회
- [ ] risk/protection/reconciliation status 조회

## Phase 3. Commands

- [ ] START_BOT command 생성
- [ ] LIVE START live_confirm 검증
- [ ] STOP_BOT command 생성
- [ ] PAUSE/RESUME command 생성
- [ ] SYNC_NOW command 생성
- [ ] command_log 저장 후 Redis publish
- [ ] DB 저장 실패 시 Redis publish 금지
- [ ] Redis 실패 시 503 반환

## Phase 4. Positions / Orders

- [ ] positions list 조회
- [ ] manual_added_qty 표시
- [ ] protection_status 표시
- [ ] external position 표시
- [ ] orders list 조회
- [ ] cancel order command 생성
- [ ] close position command 생성

## Phase 5. PnL / Events

- [ ] pnl summary 조회
- [ ] daily pnl 조회
- [ ] events 조회
- [ ] manual intervention events 조회
- [ ] TP/SL events 조회
- [ ] reconciliation events 조회

## Phase 6. Strategy Config

- [ ] config 조회
- [ ] config patch validation
- [ ] config_version 충돌 처리
- [ ] open position 중 위험 설정 변경 차단
- [ ] RELOAD_CONFIG command 생성

## Phase 7. WebSocket

- [ ] dashboard WebSocket 연결
- [ ] 연결 시 snapshot 전송
- [ ] Redis events:bot 구독
- [ ] position_update push
- [ ] pnl_update throttle
- [ ] bot_status push
- [ ] connection cleanup

## Phase 8. Failure Handling

- [ ] Redis down 시 degraded 처리
- [ ] PostgreSQL down 시 명령 발행 차단
- [ ] heartbeat timeout 처리
- [ ] malformed Redis data 처리
- [ ] WebSocket 재연결 처리

---

# 24. 구현 완료 기준

Backend API v1.0은 다음을 만족해야 한다.

```text
FastAPI 서버가 실행된다.
PostgreSQL과 Redis 연결을 관리한다.
Bot 상태를 Redis에서 조회한다.
heartbeat 기준으로 is_alive를 계산한다.
START/STOP/PAUSE/RESUME/SYNC_NOW 명령을 Redis Command Queue로 발행한다.
명령 발행 전 command_log를 PostgreSQL에 저장한다.
Backend는 Bybit API를 직접 호출하지 않는다.
현재 포지션, 주문, 체결, 거래, PnL, 이벤트를 조회할 수 있다.
manual_added_qty, EXTERNAL 포지션, TP/SL 보호 상태를 표시할 수 있다.
전략 설정을 조회/수정 요청할 수 있다.
Dashboard WebSocket으로 실시간 상태를 전달한다.
Redis 장애와 PostgreSQL 장애를 명확히 처리한다.
핵심 테스트가 통과한다.
```

---

# 25. 로그 / 데이터 보관 및 정리 정책

Backend API와 PostgreSQL은 무한 용량을 가정하면 안 된다. 모든 로그성 데이터는 보관 기간, 요약, 아카이브, 삭제 정책을 명확히 가져야 한다.

## 25.1 데이터 등급 분류

```text
CRITICAL = 거래 감사와 복구에 반드시 필요한 데이터
IMPORTANT = 전략 분석과 사용자 확인에 중요한 데이터
NORMAL = 일반 조회용 로그
VERBOSE = 디버깅용 상세 로그
```

```text
CRITICAL:
orders, fills, trades, positions, command_logs, manual_intervention_logs,
position_protection_logs, EMERGENCY_STOP, TPSL_FAILED

IMPORTANT:
signals, daily_pnl, reconciliation_logs, risk snapshots, strategy_config_history

NORMAL:
bot_events INFO, dashboard activity logs, status snapshots

VERBOSE:
raw indicator snapshots, raw scanner candidates, debug logs, heartbeat history
```

## 25.2 기본 보관 기간

```yaml
retention_policy:
  trades:
    keep_days: 1825
    archive_after_days: 365

  orders:
    keep_days: 1825
    archive_after_days: 365

  fills:
    keep_days: 1825
    archive_after_days: 365

  positions:
    keep_days: 1825
    archive_after_days: 365

  command_logs:
    keep_days: 1825
    archive_after_days: 365

  daily_pnl:
    keep_days: 1825
    archive_after_days: 365

  manual_intervention_logs:
    keep_days: 1825
    archive_after_days: 365

  position_protection_logs:
    keep_days: 1825
    archive_after_days: 365

  bot_events_info:
    keep_days: 90
    archive_after_days: 30

  bot_events_warning:
    keep_days: 365
    archive_after_days: 180

  bot_events_error:
    keep_days: 1825
    archive_after_days: 365

  reconciliation_logs:
    keep_days: 180
    archive_after_days: 30

  signal_logs:
    keep_days: 365
    archive_after_days: 90

  scanner_snapshots:
    keep_days: 30
    archive_after_days: 7

  indicator_snapshots:
    keep_days: 30
    archive_after_days: 7

  websocket_delivery_logs:
    keep_days: 7
    archive_after_days: 1

  heartbeat_history:
    keep_days: 7
    archive_after_days: 1
```

## 25.3 삭제 금지 데이터

아래 데이터는 자동 삭제하지 않고 archive만 허용한다.

```text
LIVE trades
LIVE fills
LIVE orders
LIVE command_logs
LIVE manual_intervention_logs
LIVE position_protection_logs
EMERGENCY_STOP 이벤트
TPSL_FAILED 이벤트
RISK_LOCKED 이벤트
ORDER_LOCKED 이벤트
```

## 25.4 PAPER 데이터 정리 정책

```yaml
paper_retention_policy:
  paper_orders_keep_days: 180
  paper_fills_keep_days: 180
  paper_trades_keep_days: 365
  paper_events_keep_days: 90
  paper_indicator_snapshots_keep_days: 14
  paper_scanner_snapshots_keep_days: 14
```

PAPER 상세 데이터 삭제 전 반드시 아래 요약을 생성한다.

```text
daily_pnl
daily_strategy_pnl
daily_symbol_pnl
daily_entry_mode_pnl
daily_event_summary
```

## 25.5 Archive 정책

운영 테이블에 데이터를 무한히 쌓지 않는다.

```text
orders → orders_archive
fills → fills_archive
trades → trades_archive
bot_events → bot_events_archive
reconciliation_logs → reconciliation_logs_archive
```

archive 대상:

```text
archive_after_days가 지난 데이터
조회 빈도가 낮은 데이터
거래 감사에는 필요하지만 실시간 대시보드에는 필요 없는 데이터
```

## 25.6 일일 요약 테이블

필수 요약 테이블:

```text
daily_pnl
daily_symbol_pnl
daily_strategy_pnl
daily_entry_mode_pnl
daily_event_summary
daily_manual_intervention_summary
```

일일 요약 생성 시점:

```text
매일 00:05 KST
```

## 25.7 Maintenance Job

Backend는 운영 관리 job을 둘 수 있다. 향후 별도 worker로 분리 가능해야 한다.

```yaml
maintenance_jobs:
  daily_summary:
    run_at_kst: "00:05"

  archive_job:
    run_at_kst: "00:20"

  retention_cleanup:
    run_at_kst: "00:40"

  database_health_check:
    interval_minutes: 60
```

## 25.8 날짜별 일일 로그 API

### GET /logs/daily

목적:

```text
날짜별 일일 로그 상세 조회
```

Query:

```text
date=2026-06-04
mode=PAPER
```

응답:

```json
{
  "date": "2026-06-04",
  "mode": "PAPER",
  "summary": {
    "trade_count": 12,
    "win_count": 7,
    "loss_count": 5,
    "net_pnl": "52.30",
    "max_drawdown": "1.20",
    "manual_intervention_count": 1,
    "tpsl_failed_count": 0,
    "emergency_count": 0
  },
  "sections": {
    "trades": [],
    "events": [],
    "manual_interventions": [],
    "risk_events": [],
    "protection_events": []
  }
}
```

### GET /logs/daily/calendar

목적:

```text
월간 캘린더에서 날짜별 로그 존재 여부와 요약을 표시
```

Query:

```text
year=2026
month=6
mode=PAPER
```

응답:

```json
{
  "year": 2026,
  "month": 6,
  "items": [
    {
      "date": "2026-06-04",
      "trade_count": 12,
      "net_pnl": "52.30",
      "has_warning": true,
      "has_error": false,
      "manual_intervention_count": 1
    }
  ]
}
```

## 25.9 상세 거래 로그 API

### GET /trades/{trade_id}

응답에는 다음을 포함한다.

```text
trade
orders
fills
events
manual_interventions
protection_events
risk_events
timeline
```

timeline event 예시:

```text
SIGNAL_CREATED
ORDER_CREATED
ORDER_FILLED
POSITION_OPENED
TPSL_SET
TPSL_VERIFIED
MANUAL_QTY_INCREASED
PARTIAL_TAKE_PROFIT
TRAILING_UPDATED
SCENARIO_INVALID
POSITION_CLOSED
```

## 25.10 데이터 용량 감시 API

### GET /system/storage

목적:

```text
DB 테이블 크기와 로그 증가량 확인
```

응답:

```json
{
  "database_size_mb": 512,
  "tables": [
    {
      "name": "bot_events",
      "rows": 120000,
      "size_mb": 85,
      "oldest_created_at": "2026-05-01T00:00:00Z"
    }
  ],
  "retention_status": {
    "last_cleanup_at": "2026-06-04T00:40:00Z",
    "last_archive_at": "2026-06-04T00:20:00Z"
  }
}
```

## 25.11 테스트 체크리스트 추가

- [ ] retention policy config 로드
- [ ] PAPER 로그 보관 기간 적용
- [ ] LIVE 중요 로그 삭제 금지
- [ ] archive 대상 데이터 이동
- [ ] daily summary 생성
- [ ] old verbose logs 삭제
- [ ] /logs/daily 조회
- [ ] /logs/daily/calendar 조회
- [ ] /trades/{trade_id} 상세 조회
- [ ] /system/storage 조회
- [ ] DB 장애 시 cleanup job 중단
- [ ] cleanup 전에 summary 생성 여부 확인
