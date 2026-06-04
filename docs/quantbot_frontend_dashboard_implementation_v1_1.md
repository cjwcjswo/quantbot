# QuantBot Frontend Dashboard 구현 문서 v1.1
## React + Vite + TypeScript 기반 대시보드 개발 프롬프트

## 1. 문서 목적

이 문서는 AI 개발 에이전트가 QuantBot Frontend Dashboard를 실제로 구현할 수 있도록 작성된 개발 명세다.

Frontend Dashboard의 목적은 다음과 같다.

```text
Bot Engine 상태를 시각화한다.
PAPER / LIVE 모드를 명확히 표시한다.
STANDBY / RUNNING / PAUSED / EMERGENCY_STOP 상태를 표시한다.
사용자가 START / STOP / PAUSE / RESUME / SYNC 명령을 보낼 수 있게 한다.
현재 포지션, 주문, 거래, PnL, 리스크 상태를 확인한다.
TP/SL 보호 상태를 확인한다.
수동 개입 이벤트와 manual_added_qty를 표시한다.
실시간 WebSocket 이벤트를 반영한다.
```

Frontend Dashboard는 다음을 절대 수행하지 않는다.

```text
Bybit API 직접 호출
주문 직접 실행
전략 판단
리스크 계산
포지션 관리
TP/SL 설정
```

모든 데이터와 명령은 Backend API를 통해서만 처리한다.

---

# 2. 기술 스택

권장 스택:

```text
React
Vite
TypeScript
React Router
TanStack Query
Zustand
Tailwind CSS
Recharts
Lightweight Charts optional
Axios or fetch wrapper
```

코딩 원칙:

```text
TypeScript any 사용 금지
명확한 타입 정의
API 응답 타입 정의
상태 관리는 서버 상태와 UI 상태를 분리
서버 상태는 TanStack Query
전역 UI 상태는 Zustand
실시간 이벤트는 WebSocket store로 관리
```

---

# 3. 프로젝트 구조

권장 폴더 구조:

```text
apps/
  frontend/
    src/
      app/
        App.tsx
        router.tsx
        providers.tsx

      pages/
        DashboardPage.tsx
        PositionsPage.tsx
        OrdersPage.tsx
        TradesPage.tsx
        EventsPage.tsx
        StrategyConfigPage.tsx
        SettingsPage.tsx

      features/
        bot-status/
          components/
          hooks/
          types.ts

        commands/
          components/
          hooks/
          types.ts

        positions/
          components/
          hooks/
          types.ts

        orders/
          components/
          hooks/
          types.ts

        pnl/
          components/
          hooks/
          types.ts

        events/
          components/
          hooks/
          types.ts

        strategy-config/
          components/
          hooks/
          types.ts

        websocket/
          useDashboardSocket.ts
          websocketStore.ts
          types.ts

      shared/
        api/
          client.ts
          endpoints.ts
          types.ts

        components/
          Layout.tsx
          Header.tsx
          Sidebar.tsx
          StatusBadge.tsx
          ConfirmDialog.tsx
          DataTable.tsx
          MetricCard.tsx
          ErrorState.tsx
          LoadingState.tsx

        utils/
          formatNumber.ts
          formatDate.ts
          formatPnl.ts

        styles/
          index.css

      main.tsx
```

---

# 4. 화면 구성

## 4.1 기본 페이지

```text
Dashboard
Positions
Orders
Trades
Events
Strategy Config
Settings
```

## 4.2 Layout

공통 레이아웃:

```text
상단 Header
좌측 Sidebar
중앙 Content
하단 또는 우측 실시간 이벤트 토스트 영역
```

Header 표시 항목:

```text
Bot State
Mode: PAPER / LIVE
Heartbeat 상태
Risk 상태
TP/SL Protection 상태
Reconciliation 상태
현재 시간
```

---

# 5. Bot 상태 표시

## 5.1 상태 값

Bot State 허용값:

```text
BOOTING
STANDBY
START_REQUESTED
SYNCING
READY
RUNNING
PAUSED
RISK_LOCKED
RECONCILING
ORDER_LOCKED
EMERGENCY_STOP
STOPPING
STOPPED
UNKNOWN
DISCONNECTED
```

## 5.2 상태 색상 규칙

```text
RUNNING = green
STANDBY = gray
PAUSED = yellow
SYNCING / RECONCILING = blue
RISK_LOCKED / ORDER_LOCKED = orange
EMERGENCY_STOP = red
DISCONNECTED / UNKNOWN = red
```

## 5.3 Mode 표시

Mode:

```text
PAPER
LIVE
```

LIVE 모드는 반드시 눈에 띄게 표시한다.

```text
LIVE badge = red
PAPER badge = gray or blue
```

LIVE 모드 START 버튼 클릭 시 추가 확인 dialog를 띄운다.

확인 문구:

```text
LIVE 모드로 실제 주문이 실행됩니다. 계속하려면 LIVE를 입력하세요.
```

사용자가 `LIVE`를 정확히 입력해야 START 요청 가능.

---

# 6. Dashboard Page

Dashboard는 전체 상태 요약 화면이다.

## 6.1 Metric Cards

표시 카드:

```text
Bot State
Mode
Equity
Daily Net PnL
Open Positions
Open Risk
Realized PnL
Unrealized PnL
Fees
Funding Fees
Heartbeat
TP/SL Protection
Reconciliation
```

## 6.2 Main Panels

```text
PnL Summary Chart
Current Positions Table
Recent Orders
Recent Trades
Recent Events
Risk Status Panel
Protection Status Panel
Manual Intervention Panel
```

---

# 7. Command Controls

## 7.1 버튼

```text
START
STOP
PAUSE
RESUME
SYNC NOW
```

위험 버튼:

```text
START LIVE
STOP with close positions
CLOSE POSITION
CANCEL ORDER
```

위험 버튼은 ConfirmDialog 필수.

---

## 7.2 START 버튼 동작

PAPER START:

```text
1. 사용자가 START 클릭
2. mode=PAPER 선택
3. POST /bot/start 호출
4. command_id 표시
5. Bot 상태가 START_REQUESTED / SYNCING / RUNNING으로 변하는 것을 WebSocket으로 반영
```

LIVE START:

```text
1. 사용자가 START 클릭
2. mode=LIVE 선택
3. ConfirmDialog 표시
4. 사용자가 LIVE 입력
5. POST /bot/start { mode: "LIVE", live_confirm: true }
6. command_id 표시
```

Bot 상태가 이미 RUNNING이면 START 버튼 비활성화.

---

## 7.3 STOP 버튼 동작

STOP 요청 payload:

```json
{
  "close_positions": false,
  "cancel_open_orders": true
}
```

UI 옵션:

```text
Open orders cancel 여부 checkbox
Positions close 여부 checkbox
```

기본값:

```text
cancel_open_orders = true
close_positions = false
```

`close_positions=true` 선택 시 강한 경고 dialog 표시.

---

## 7.4 PAUSE / RESUME

PAUSE:

```text
신규 진입 중지
기존 봇 포지션 관리는 계속
```

RESUME:

```text
PAUSED 상태에서만 활성화
RISK_LOCKED / EMERGENCY_STOP에서는 비활성화
```

---

## 7.5 SYNC NOW

목적:

```text
Bot Engine에 즉시 Bybit 상태 동기화 요청
```

동작:

```text
POST /bot/sync
```

---

# 8. Positions Page

## 8.1 Columns

포지션 테이블 컬럼:

```text
Symbol
Side
Source
Mode
Qty
Manual Added Qty
Avg Entry
Mark Price
Unrealized PnL
Unrealized PnL %
Leverage
Entry Mode
Strategy
Protection Status
Stop Loss
Take Profit
Opened At
Actions
```

## 8.2 Source 표시

source 값:

```text
BOT
EXTERNAL
MANUAL_ADDED
```

표시 규칙:

```text
BOT = 일반
EXTERNAL = 경고 아이콘
MANUAL_ADDED = 수동 증가 표시
```

`manual_added_qty > 0`이면 별도 배지 표시:

```text
Manual Added
```

## 8.3 Protection Status

허용값:

```text
TPSL_OK
TPSL_PENDING
TPSL_FAILED
NOT_REQUIRED
UNKNOWN
```

색상:

```text
TPSL_OK = green
TPSL_PENDING = blue
TPSL_FAILED = red
NOT_REQUIRED = gray
UNKNOWN = yellow
```

LIVE 포지션인데 `TPSL_OK`가 아니면 경고 표시.

---

## 8.4 Close Position

Close 버튼 클릭 시 ConfirmDialog.

요청:

```json
{
  "close_percent": 100,
  "reason": "manual dashboard close"
}
```

옵션:

```text
25%
50%
100%
custom percent
```

Backend 호출:

```text
POST /positions/{symbol}/close
```

---

# 9. Orders Page

## 9.1 Columns

```text
Order ID
Symbol
Side
Order Type
Status
Source
Mode
Qty
Filled Qty
Price
Avg Fill Price
Reduce Only
Created At
Updated At
Actions
```

## 9.2 Status

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

## 9.3 Cancel Order

취소 가능한 상태:

```text
NEW
PARTIALLY_FILLED
UNKNOWN
```

Cancel 클릭:

```text
ConfirmDialog
→ POST /orders/{order_id}/cancel
```

---

# 10. Trades Page

## 10.1 Columns

```text
Trade ID
Symbol
Side
Strategy
Entry Mode
Mode
Entry Price
Exit Price
Qty
Gross PnL
Fees
Funding
Net PnL
R Multiple
Exit Reason
Opened At
Closed At
```

## 10.2 필터

```text
Symbol
Strategy
Entry Mode
Mode
Date Range
PnL positive/negative
Exit Reason
```

---

# 11. Events Page

## 11.1 Columns

```text
Timestamp
Severity
Event Type
Symbol
Message
Details
```

## 11.2 Event Type

표시 대상:

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

위험 이벤트는 강조:

```text
EMERGENCY_STOP
TPSL_FAILED
ORDER_LOCKED
RISK_LOCKED
MANUAL_INTERVENTION_DETECTED
```

---

# 12. Strategy Config Page

## 12.1 목적

전략 설정을 조회하고 수정 요청을 보낸다.

Frontend는 설정을 직접 적용하지 않는다.

```text
Frontend
→ Backend PUT /strategy/config
→ Backend validation
→ Redis RELOAD_CONFIG command
→ Bot Engine 적용
```

## 12.2 표시 섹션

```text
Bot
Paper
Universe
Scanner
Trend Quality
Volume
Candle Quality
Entry
Orders
Risk
Liquidation Guard
TP/SL
Position Protection
Cooldown
Global Kill Switch
Reconciliation
Manual Intervention
Data Quality
Funding Guard
```

## 12.3 수정 정책

위험 설정 변경 시 ConfirmDialog.

위험 설정:

```text
risk
leverage
stop_loss
tpsl
global_kill_switch
position_protection
orders
```

open position이 있을 때 Backend가 위험 설정 변경을 거부할 수 있다.  
Frontend는 거부 응답을 사용자에게 표시한다.

---

# 13. WebSocket 연동

## 13.1 연결

```text
ws://localhost:8000/ws/dashboard
```

## 13.2 이벤트 타입

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

## 13.3 클라이언트 처리

연결 성공 시:

```text
connected=true
```

연결 끊김:

```text
connected=false
상단에 DISCONNECTED 표시
3초 후 재연결 시도
재연결 backoff 최대 30초
```

재연결 후:

```text
REST snapshot 재조회
WebSocket 이벤트 다시 수신
```

## 13.4 이벤트 반영 원칙

```text
WebSocket 이벤트는 UI 즉시 반영용
최종 상태는 REST snapshot 또는 Redis snapshot 기준
이벤트 누락 가능성을 고려해 주기적으로 REST refetch 수행
```

권장 refetch:

```text
bot status: 5초
positions: 5초
pnl: 5초
orders: 10초
events: 15초
```

---

# 14. API Client

## 14.1 공통 타입

```ts
export type ApiResponse<T> = {
  ok: boolean;
  data: T | null;
  error: ApiError | null;
};

export type ApiError = {
  code: string;
  message: string;
  details: Record<string, unknown>;
};
```

`any` 사용 금지.  
불명확한 details는 `Record<string, unknown>` 사용.

## 14.2 BotStatus 타입

```ts
export type BotState =
  | "BOOTING"
  | "STANDBY"
  | "START_REQUESTED"
  | "SYNCING"
  | "READY"
  | "RUNNING"
  | "PAUSED"
  | "RISK_LOCKED"
  | "RECONCILING"
  | "ORDER_LOCKED"
  | "EMERGENCY_STOP"
  | "STOPPING"
  | "STOPPED"
  | "UNKNOWN"
  | "DISCONNECTED";

export type BotMode = "PAPER" | "LIVE";

export type BotStatus = {
  state: BotState;
  mode: BotMode;
  heartbeatAt: string | null;
  isAlive: boolean;
  isTradingEnabled: boolean;
  riskStatus: string;
  protectionStatus: string;
  reconciliationStatus: string;
};
```

## 14.3 Position 타입

```ts
export type PositionSource = "BOT" | "EXTERNAL" | "MANUAL_ADDED";
export type PositionSide = "LONG" | "SHORT";
export type ProtectionStatus =
  | "TPSL_OK"
  | "TPSL_PENDING"
  | "TPSL_FAILED"
  | "NOT_REQUIRED"
  | "UNKNOWN";

export type Position = {
  symbol: string;
  side: PositionSide;
  source: PositionSource;
  mode: BotMode;
  qty: string;
  manualAddedQty: string;
  avgEntryPrice: string;
  markPrice: string;
  unrealizedPnl: string;
  unrealizedPnlPercent: string;
  leverage: string;
  entryMode: string | null;
  strategyId: string | null;
  protectionStatus: ProtectionStatus;
  stopLossPrice: string | null;
  takeProfitPrice: string | null;
  openedAt: string;
};
```

---

# 15. 상태 관리

## 15.1 TanStack Query

서버 상태:

```text
bot status
positions
orders
trades
pnl
events
strategy config
```

## 15.2 Zustand

UI 상태:

```text
sidebar open/closed
selected symbol
theme
websocket connection status
recent realtime events
toasts
confirm dialog state
```

---

# 16. UX 안전 장치

## 16.1 LIVE 모드 강조

LIVE 상태에서는 항상 상단에 빨간 배너 표시.

```text
LIVE MODE - Real orders are enabled
```

## 16.2 위험 명령 확인

위험 명령은 ConfirmDialog 필수.

```text
START LIVE
STOP with close_positions=true
CLOSE POSITION
CANCEL ORDER
Strategy Config 위험 변경
```

## 16.3 Bot 비정상 상태

아래 상태에서는 START/RESUME 버튼 비활성화 또는 제한.

```text
EMERGENCY_STOP
RISK_LOCKED
ORDER_LOCKED
DISCONNECTED
UNKNOWN
```

## 16.4 TP/SL 실패 경고

LIVE 포지션에서 protection_status가 `TPSL_FAILED`이면 다음 표시:

```text
빨간 경고
상단 alert
Events 페이지 강조
Position row 강조
```

---

# 17. 에러 처리

## 17.1 API 실패

API 실패 시:

```text
Toast 표시
해당 컴포넌트 ErrorState 표시
재시도 버튼 제공
```

## 17.2 명령 실패

명령 생성 실패:

```text
에러 메시지 표시
command_id가 없으면 명령 발행 실패로 표시
```

명령 생성 성공:

```text
command_id 표시
처리 결과는 Events 또는 Bot Status에서 확인
```

## 17.3 WebSocket 실패

```text
상단 DISCONNECTED 표시
자동 재연결
재연결 후 REST snapshot 재조회
```

---

# 18. 테스트 체크리스트

## Phase 1. 기본 화면

- [ ] App boot
- [ ] Router 설정
- [ ] Layout 표시
- [ ] Header / Sidebar 표시
- [ ] Tailwind 적용

## Phase 2. API Client

- [ ] 공통 ApiResponse 타입
- [ ] error handling
- [ ] bot status fetch
- [ ] positions fetch
- [ ] orders fetch
- [ ] pnl fetch
- [ ] events fetch
- [ ] strategy config fetch

## Phase 3. Dashboard

- [ ] Bot State 표시
- [ ] PAPER/LIVE 표시
- [ ] heartbeat 표시
- [ ] PnL 카드 표시
- [ ] positions summary 표시
- [ ] recent events 표시
- [ ] TP/SL protection 표시
- [ ] reconciliation 표시

## Phase 4. Commands

- [ ] PAPER START
- [ ] LIVE START confirm input
- [ ] STOP
- [ ] PAUSE
- [ ] RESUME
- [ ] SYNC NOW
- [ ] command_id 표시
- [ ] API error 표시

## Phase 5. Positions

- [ ] positions table
- [ ] manual_added_qty 표시
- [ ] EXTERNAL 표시
- [ ] protection_status 표시
- [ ] close position dialog
- [ ] close percent validation

## Phase 6. Orders / Trades

- [ ] orders table
- [ ] order status badge
- [ ] cancel order dialog
- [ ] trades table
- [ ] PnL formatting
- [ ] filters

## Phase 7. Events

- [ ] events table
- [ ] severity badge
- [ ] event type filter
- [ ] dangerous event 강조
- [ ] details 펼침

## Phase 8. Strategy Config

- [ ] config 조회
- [ ] config form 표시
- [ ] 위험 설정 confirm
- [ ] PUT /strategy/config 호출
- [ ] validation error 표시
- [ ] config_version conflict 표시

## Phase 9. WebSocket

- [ ] WS 연결
- [ ] reconnect
- [ ] bot_status event 반영
- [ ] position_update 반영
- [ ] pnl_update throttle 반영
- [ ] disconnected 표시
- [ ] reconnect 후 REST refetch

## Phase 10. Safety UX

- [ ] LIVE red banner
- [ ] EMERGENCY_STOP red alert
- [ ] TPSL_FAILED alert
- [ ] DISCONNECTED alert
- [ ] 위험 명령 confirm
- [ ] START disabled when RUNNING

---

# 19. 구현 완료 기준

Frontend Dashboard v1.0은 다음을 만족해야 한다.

```text
React + Vite + TypeScript로 실행된다.
Backend API와 통신한다.
Dashboard에서 Bot 상태를 표시한다.
PAPER / LIVE 모드를 명확히 표시한다.
STANDBY 상태에서 START 버튼을 제공한다.
LIVE START 시 LIVE 입력 확인을 요구한다.
START/STOP/PAUSE/RESUME/SYNC 명령을 보낼 수 있다.
현재 포지션 목록을 표시한다.
manual_added_qty를 표시한다.
EXTERNAL / MANUAL_ADDED 상태를 표시한다.
TP/SL protection_status를 표시한다.
주문, 거래, 이벤트, PnL을 조회한다.
WebSocket으로 실시간 상태를 반영한다.
WebSocket 끊김 시 재연결하고 REST snapshot을 재조회한다.
위험 명령에는 ConfirmDialog를 표시한다.
TypeScript any를 사용하지 않는다.
핵심 테스트가 통과한다.
```

---

# 20. 디자인 시스템 / UI 품질 기준

Frontend Dashboard는 단순 기능 나열이 아니라 실제 운영자가 오래 켜두고 볼 수 있는 깔끔한 관제 UI로 구현한다.

## 20.1 디자인 방향

```text
Clean
Dark-first
Trading Dashboard
Readable
Low noise
High contrast for risk
```

기본 테마:

```text
Dark mode 우선
Light mode는 후순위
배경은 어두운 slate 계열
카드는 은은한 border와 shadow
위험 상태만 강한 색상 사용
```

권장 Tailwind 기준:

```text
background: slate-950
panel: slate-900
panel border: slate-800
text primary: slate-100
text secondary: slate-400
positive: emerald
negative: rose
warning: amber
info: sky
danger: red
```

## 20.2 화면 밀도

```text
한 화면에서 Bot 상태, PnL, 포지션, 이벤트를 빠르게 파악할 수 있어야 한다.
숫자는 오른쪽 정렬한다.
PnL은 양수/음수 색상을 명확히 구분한다.
위험 상태는 badge + icon + alert로 중복 표시한다.
```

## 20.3 공통 컴포넌트

```text
MetricCard
StatusBadge
ModeBadge
RiskBadge
ProtectionBadge
CommandButton
DangerButton
DataTable
EmptyState
LoadingSkeleton
ErrorState
ConfirmDialog
DailyLogModal
TradeDetailDrawer
```

버튼 규칙:

```text
START PAPER = primary
START LIVE = danger
PAUSE = warning
RESUME = primary
STOP = danger outline
SYNC NOW = secondary
```

---

# 21. 상세 거래 로그 UX

기존 Trades Page는 거래 목록 중심이다. v1.1에서는 개별 거래의 전체 생명주기를 볼 수 있는 상세 로그를 추가한다.

## 21.1 Trade Detail Drawer

거래 row 클릭 시 우측 Drawer를 연다.

표시 정보:

```text
기본 정보:
- trade_id
- symbol
- mode
- side
- strategy_id
- entry_mode
- source
- opened_at
- closed_at
- duration

진입 정보:
- signal_created_at
- signal_score
- strategy_reason
- entry_price
- qty
- manual_added_qty
- leverage
- risk_usdt
- stop_loss_price
- take_profit_price

체결 정보:
- orders
- fills
- avg_fill_price
- fees
- slippage

관리 정보:
- partial take profit events
- trailing stop updates
- scenario invalid events
- stagnation exit events
- TP/SL set / verified events

청산 정보:
- exit_price
- exit_reason
- gross_pnl
- net_pnl
- r_multiple
- fees
- funding_fees

관련 이벤트:
- reconciliation events
- manual intervention events
- protection events
- risk events
```

## 21.2 Timeline 표시

Drawer 내부에 timeline을 표시한다.

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

Timeline UI:

```text
시간순 정렬
severity별 색상
클릭 시 raw JSON details 펼침
```

---

# 22. 날짜별 일일 로그 모달

Dashboard 또는 Events Page에서 날짜를 선택하면 일일 로그 모달을 띄운다.

## 22.1 Daily Log Calendar

Dashboard에 작은 월간 캘린더 또는 날짜 선택 버튼을 둔다.

표시 정보:

```text
날짜별 trade_count
날짜별 net_pnl
warning/error 존재 여부
manual intervention 여부
```

색상:

```text
net_pnl > 0 = emerald
net_pnl < 0 = rose
warning 있음 = amber dot
error 있음 = red dot
manual intervention 있음 = purple dot
```

## 22.2 DailyLogModal

모달 제목:

```text
Daily Log - 2026-06-04 / PAPER
```

상단 Summary:

```text
총 거래 수
승/패
승률
Net PnL
Realized PnL
Unrealized PnL
Fees
Max Drawdown
Manual Intervention Count
TP/SL Failed Count
Emergency Count
```

탭 구성:

```text
Summary
Trades
Events
Manual
Risk
Protection
Raw
```

## 22.3 Summary 탭

표시:

```text
PnL mini chart
전략별 손익
심볼별 손익
entry_mode별 손익
시간대별 거래 수
```

## 22.4 Trades 탭

컬럼:

```text
Time
Symbol
Side
Entry Mode
Qty
Entry
Exit
Net PnL
R
Exit Reason
```

row 클릭 시 TradeDetailDrawer 오픈.

## 22.5 Events 탭

컬럼:

```text
Time
Severity
Event Type
Symbol
Message
```

필터:

```text
INFO
WARNING
ERROR
CRITICAL
```

## 22.6 Manual 탭

수동 개입 내역 표시:

```text
MANUAL_QTY_INCREASED
MANUAL_QTY_DECREASED
EXTERNAL_ORDER_DETECTED
EXTERNAL_POSITION_DETECTED
```

표시 필드:

```text
time
symbol
before_qty
after_qty
manual_added_qty
avg_price_before
avg_price_after
action_taken
```

## 22.7 Risk 탭

표시:

```text
daily loss guard
drawdown guard
cooldown events
risk rejected signals
position sizing changes
leverage limit events
```

## 22.8 Protection 탭

표시:

```text
TPSL_SET
TPSL_VERIFIED
TPSL_FAILED
EMERGENCY_TPSL_FAILED
emergency close events
```

## 22.9 Raw 탭

개발/디버깅용 raw JSON 표시.

```text
기본 접힘 상태
Copy JSON 버튼 제공
민감정보는 표시하지 않음
```

---

# 23. API 연동 추가

## 23.1 Daily Log API

사용 API:

```text
GET /logs/daily?date=YYYY-MM-DD&mode=PAPER
GET /logs/daily/calendar?year=2026&month=6&mode=PAPER
```

TypeScript 타입:

```ts
export type DailyLogCalendarItem = {
  date: string;
  tradeCount: number;
  netPnl: string;
  hasWarning: boolean;
  hasError: boolean;
  manualInterventionCount: number;
};

export type DailyLogSummary = {
  date: string;
  mode: BotMode;
  tradeCount: number;
  winCount: number;
  lossCount: number;
  netPnl: string;
  realizedPnl: string;
  unrealizedPnl: string;
  fees: string;
  maxDrawdown: string;
  manualInterventionCount: number;
  tpslFailedCount: number;
  emergencyCount: number;
};
```

## 23.2 Trade Detail API

사용 API:

```text
GET /trades/{trade_id}
```

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

---

# 24. Frontend 테스트 체크리스트 추가

## 디자인

- [ ] Dark-first 레이아웃 적용
- [ ] MetricCard 통일
- [ ] StatusBadge 색상 규칙 적용
- [ ] LIVE red banner 적용
- [ ] 위험 상태 alert 적용
- [ ] 테이블 숫자 오른쪽 정렬
- [ ] Empty/Loading/Error 상태 구현

## 상세 거래 로그

- [ ] Trade row 클릭 시 Drawer 오픈
- [ ] 거래 기본 정보 표시
- [ ] 주문/체결 정보 표시
- [ ] TP/SL 보호 이벤트 표시
- [ ] manual_added_qty 표시
- [ ] timeline 표시
- [ ] raw JSON details 펼침

## 일일 로그 모달

- [ ] 날짜 선택 UI
- [ ] 월간 calendar summary 조회
- [ ] DailyLogModal 오픈
- [ ] Summary 탭
- [ ] Trades 탭
- [ ] Events 탭
- [ ] Manual 탭
- [ ] Risk 탭
- [ ] Protection 탭
- [ ] Raw 탭
- [ ] row 클릭 시 TradeDetailDrawer 연동

---

# 25. 구현 완료 기준 추가

Frontend Dashboard v1.1은 다음을 추가로 만족해야 한다.

```text
깔끔한 dark-first trading dashboard 디자인을 제공한다.
Bot 상태, PnL, 포지션, 위험 상태가 한눈에 들어온다.
상세 거래 로그를 Drawer로 확인할 수 있다.
거래별 전체 timeline을 볼 수 있다.
날짜별 일일 로그를 모달로 확인할 수 있다.
월간 캘린더에서 날짜별 PnL과 경고 여부를 확인할 수 있다.
Manual / Risk / Protection 로그를 일일 단위로 분리해서 볼 수 있다.
LIVE 위험 상태와 TPSL_FAILED 상태가 시각적으로 강하게 표시된다.
```
