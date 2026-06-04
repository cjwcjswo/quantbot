# QuantBot 서버 아키텍처 문서 v1.2

## 1. 문서 목적

이 문서는 QuantBot 시스템의 서버 아키텍처와 각 구성요소의 역할을 정의한다.

v1.2에서는 기존 v1.1 아키텍처에 Bot Engine v1.3.1에서 확정된 운영 정책을 반영한다.

반영된 핵심 변경사항:

```text
Bot은 프로그램 시작과 동시에 매매하지 않고 STANDBY 상태로 대기한다.
Frontend/Backend의 START 명령 이후에만 RUNNING 상태로 전환된다.
Bot Engine은 PAPER / LIVE 모드를 모두 지원한다.
PAPER 모드는 실제 Bybit 시장 데이터와 가상 자산을 사용한다.
LIVE 모드는 실제 Bybit 계좌와 주문을 사용한다.
Bybit 실제 상태를 주기적으로 동기화한다.
Bybit 상태를 최종 진실(source of truth)로 사용한다.
Bybit 앱 수동 주문/수동 수량 변경은 비상 개입으로 간주하고 내부 상태에 반영한다.
LIVE 진입 후 TP/SL 보호 설정과 검증을 Bot Engine 책임으로 둔다.
```

본 문서는 다음 주제에 집중한다.

```text
전체 서버 구성
서비스 간 책임 분리
Bot Engine과 Backend API의 분리
Bot Engine 내부 모듈 책임
PAPER / LIVE 실행 구조
Bot State Machine
Bybit 상태 동기화 구조
TP/SL 보호 구조
수동 개입 반영 구조
전략 AddOn 구조
서비스 간 데이터 흐름
```

본 문서에서는 다음 내용은 다루지 않는다.

```text
구체적인 매매 전략 세부 수치
진입/청산 조건 상세
백테스트 상세 설계
대시보드 UI 상세
데이터베이스 테이블 상세 DDL
배포 자동화 상세
운영 모니터링 상세
```

---

## 2. 전체 아키텍처 개요

QuantBot은 다음 서비스로 구성한다.

```text
Frontend Dashboard
= 사용자 대시보드

Backend API
= 데이터 조회, 설정 관리, 봇 제어 API

Bot Engine
= 실시간 시장 데이터 처리, 전략 판단, 주문 실행, 포지션 관리, Bybit 상태 동기화

PostgreSQL
= 영구 데이터 저장소

Redis
= 실시간 상태 공유, 명령 전달, 런타임 락, 이벤트 pub/sub

External Exchange
= Bybit API / WebSocket
```

전체 구조는 다음과 같다.

```text
┌──────────────────────────────┐
│ Frontend Dashboard            │
│ React + Vite + TypeScript     │
└───────────────┬──────────────┘
                │
                │ HTTP / WebSocket
                ▼
┌──────────────────────────────┐
│ Backend API                   │
│ FastAPI                       │
│ - REST API                    │
│ - WebSocket API               │
│ - Dashboard Data API          │
│ - Bot Command API             │
│ - Config API                  │
└───────────────┬──────────────┘
                │
                │ Read / Write
                ▼
┌──────────────────────────────┐
│ PostgreSQL                    │
│ - Trades                      │
│ - Orders                      │
│ - Fills                       │
│ - Positions                   │
│ - Bot State                   │
│ - Strategy Config             │
│ - Command Log                 │
│ - Reconciliation Log          │
│ - Manual Intervention Log     │
│ - Bot Events                  │
└───────────────▲──────────────┘
                │
                │ Persist
                │
┌───────────────┴──────────────┐
│ Redis                         │
│ - Realtime State              │
│ - Pub/Sub                     │
│ - Command Queue               │
│ - Heartbeat                   │
│ - Runtime Lock                │
│ - Dashboard Event Stream      │
└───────────────▲──────────────┘
                │
                │ Commands / Events
                ▼
┌──────────────────────────────┐
│ Quant Bot Engine              │
│ Python Worker / Service       │
│ - BotRuntime                  │
│ - BotStateMachine             │
│ - CommandConsumer             │
│ - ExchangeGateway             │
│ - ReconciliationManager       │
│ - ManualInterventionHandler   │
│ - PaperExecutionEngine        │
│ - UniverseManager             │
│ - SymbolScanner               │
│ - MarketDataCollector         │
│ - CandleStore                 │
│ - IndicatorEngine             │
│ - StrategyRegistry            │
│ - StrategyModules             │
│ - SignalEngine                │
│ - EntryTimingEngine           │
│ - RiskManager                 │
│ - OrderManager                │
│ - PositionManager             │
│ - PositionProtectionManager   │
│ - TradeLogger                 │
│ - StatePublisher              │
└───────────────┬──────────────┘
                │
                │ REST / WebSocket
                ▼
┌──────────────────────────────┐
│ Bybit API / WebSocket         │
└──────────────────────────────┘
```

---

## 3. 핵심 설계 원칙

### 3.1 Bot Engine과 Backend API는 분리한다

Bot Engine은 Backend API 내부에서 실행하지 않는다.

```text
Backend API
= 관제, 조회, 설정 관리, 명령 전달

Bot Engine
= 실시간 매매 판단, 주문 실행, 포지션 관리, 거래소 동기화
```

분리 이유:

```text
API 서버 재시작이 봇 실행에 영향을 주지 않도록 한다.
대시보드 트래픽이 봇 처리 속도에 영향을 주지 않도록 한다.
봇 장애가 API 서버 전체 장애로 전파되지 않도록 한다.
API worker 다중 실행 시 봇 중복 실행을 방지한다.
주문 권한을 Bot Engine에만 집중한다.
```

---

### 3.2 Backend API는 직접 주문하지 않는다

Backend API는 Bybit 주문 API를 직접 호출하지 않는다.

```text
Frontend
→ Backend API
→ Redis Command Queue
→ Bot Engine
→ Bybit API
```

실제 주문 실행 권한은 Bot Engine에만 둔다.

Backend API는 다음만 수행한다.

```text
사용자 요청 검증
명령 생성
명령 로그 저장
Redis Command Queue 발행
Bot 상태 조회
Dashboard 데이터 제공
```

---

### 3.3 Bot Engine은 단일 실행을 보장한다

실전 매매 Bot Engine은 중복 실행되면 안 된다.

Bot Engine 시작 시 Redis runtime lock을 획득한다.

```text
lock:quantbot:live
```

lock 획득 실패 시 Bot Engine은 실행을 중단한다.

중복 실행 방지 목적:

```text
동일 신호 중복 주문 방지
동일 포지션 중복 청산 방지
리스크 계산 중복 방지
거래소 상태와 내부 상태 불일치 방지
```

---

### 3.4 프로그램 시작과 매매 시작은 다르다

QuantBot 프로그램이 실행되었다고 자동으로 매매를 시작하면 안 된다.

기본 흐름:

```text
프로그램 실행
→ BOOTING
→ STANDBY
```

사용자가 Frontend Dashboard에서 START 버튼을 누르면 Backend API가 `START_BOT` 명령을 생성하고, Bot Engine이 이를 수신한 뒤에만 RUNNING으로 전환한다.

```text
Frontend START
→ Backend API
→ Redis Command Queue
→ CommandConsumer
→ BotStateMachine
→ START_REQUESTED
→ SYNCING
→ READY
→ RUNNING
```

---

### 3.5 PAPER와 LIVE는 동일한 아키텍처 위에서 실행한다

Bot Engine은 PAPER와 LIVE 모드를 모두 지원한다.

```text
PAPER
= 실제 Bybit 시장 데이터 + 가상 자산 + 가상 시장가 체결

LIVE
= 실제 Bybit 시장 데이터 + 실제 Bybit 계좌 + 실제 주문
```

PAPER와 LIVE는 동일한 전략, 리스크, 포지션 관리 흐름을 사용한다.

차이점은 주문 실행 레이어에 있다.

```text
PAPER
→ PaperExecutionEngine

LIVE
→ OrderManager
→ ExchangeGateway
→ Bybit API
```

---

### 3.6 Bybit 실제 상태를 최종 진실로 사용한다

Bot Engine은 주기적으로 Bybit 실제 상태와 내부 상태를 동기화한다.

```text
source_of_truth = Bybit
```

동기화 대상:

```text
포지션
수량
평균 진입가
미체결 주문
체결 이벤트
TP/SL 상태
잔고
```

Bybit 앱에서 수동 주문을 넣거나 수동으로 포지션 수량을 변경한 경우에도 Bot Engine은 Bybit 실제 상태를 기준으로 내부 상태를 보정한다.

---

### 3.7 수동 개입은 비상 개입으로 간주한다

Bybit 앱을 통한 수동 주문/수동 포지션 변경은 허용하되, 비상 개입으로 간주한다.

원칙:

```text
수동 개입을 감지하면 내부 상태를 Bybit 상태에 맞춘다.
수동 개입을 신규 전략 신호로 간주하지 않는다.
수동 개입 이후 일정 시간 신규 진입을 중지한다.
수동 증가 수량은 내부 포지션 수량에 반영한다.
수동 증가분은 manual_added_qty로 별도 기록한다.
```

---

### 3.8 LIVE 포지션은 TP/SL 보호가 확인되어야 ACTIVE가 된다

LIVE에서 포지션이 체결되면 Bot Engine은 Bybit TP/SL 설정과 검증을 수행한다.

```text
진입 체결
→ 포지션 조회
→ TP/SL 설정
→ TP/SL 재조회 검증
→ ACTIVE
```

TP/SL 설정 또는 검증 실패 시 해당 포지션은 ACTIVE가 될 수 없다.

실패 시 처리:

```text
신규 진입 중지
reduce-only MARKET 청산 시도
이벤트 기록
필요 시 EMERGENCY_STOP 전환
```

---

### 3.9 전략은 AddOn 구조로 설계한다

현재 v1에서는 추세 추종 전략만 구현한다.

그러나 아키텍처는 향후 다음 전략을 AddOn처럼 추가할 수 있게 설계한다.

```text
Trend Following Strategy
Range Strategy
Shock Reversal Strategy
Funding Strategy
Other Strategy Modules
```

중요 원칙:

```text
전략은 주문하지 않는다.
전략은 리스크를 최종 승인하지 않는다.
전략은 신호만 생성한다.
```

---

### 3.10 필터링과 진입 타이밍은 분리한다

코인을 고르는 작업과 실제 진입 타이밍을 결정하는 작업은 분리한다.

```text
SymbolScanner
= 어떤 코인을 볼지 고른다.

StrategyModule / SignalEngine
= 방향성 후보를 만든다.

EntryTimingEngine
= 지금 진입할지, 대기할지, 어떤 entry mode인지 판단한다.

RiskManager
= 실제 주문을 허용할지 결정한다.

OrderManager / PaperExecutionEngine
= 주문 또는 가상 주문을 실행한다.
```

---

## 4. Frontend Dashboard

### 4.1 역할

Frontend Dashboard는 QuantBot의 상태를 조회하고 제어하는 웹 인터페이스다.

역할:

```text
봇 실행 상태 표시
STANDBY / RUNNING / PAUSED / EMERGENCY_STOP 상태 표시
PAPER / LIVE 모드 표시
계좌 상태 표시
현재 포지션 표시
EXTERNAL / MANUAL_ADDED 포지션 상태 표시
주문 내역 표시
거래 내역 표시
실시간 PnL 표시
전략 설정 표시
봇 START / STOP / PAUSE / RESUME 요청
포지션 청산 요청
리스크 상태 표시
TP/SL 보호 상태 표시
동기화 상태 표시
수동 개입 이벤트 표시
```

Frontend Dashboard는 다음을 수행하지 않는다.

```text
Bybit API 직접 호출
전략 판단
주문 실행
리스크 계산
포지션 관리
TP/SL 직접 설정
```

---

## 5. Backend API

### 5.1 역할

Backend API는 Frontend Dashboard와 Bot Engine 사이의 관제 계층이다.

역할:

```text
Dashboard용 REST API 제공
Dashboard용 WebSocket 제공
PostgreSQL 데이터 조회
Redis 실시간 상태 조회
Bot Command 생성
Strategy Config 조회/수정
Bot Mode 조회
PAPER / LIVE 모드 상태 조회
사용자 요청 검증
시스템 상태 제공
```

Backend API는 다음을 수행하지 않는다.

```text
실시간 시장 데이터 수신
전략 신호 생성
주문 직접 실행
포지션 직접 관리
손절/익절 판단
TP/SL 직접 설정
트레일링 스탑 계산
Bybit API 직접 주문 호출
```

### 5.2 주요 명령

Backend API는 Redis Command Queue에 다음 명령을 발행한다.

```text
START_BOT
STOP_BOT
PAUSE_TRADING
RESUME_TRADING
RELOAD_CONFIG
CLOSE_POSITION
CANCEL_ORDER
SYNC_NOW
```

### 5.3 START 명령 책임

START 명령은 매매 시작의 트리거다.

```text
프로그램 실행만으로는 매매 시작 금지
Frontend START 요청
→ Backend API 요청 검증
→ command_log 저장
→ Redis Command Queue 발행
→ Bot Engine이 START_REQUESTED로 전환
```

---

## 6. Quant Bot Engine

### 6.1 역할

Quant Bot Engine은 실제 매매 시스템의 핵심 서비스다.

역할:

```text
Bot State Machine 관리
PAPER / LIVE 실행 모드 관리
Bybit WebSocket 연결
Bybit REST API 호출
시장 데이터 수신
캔들 데이터 관리
지표 계산
감시 대상 코인 선정
전략 신호 생성
진입 타이밍 판단
리스크 검증
PAPER 가상 주문 실행
LIVE 실제 주문 실행
TP/SL 설정 및 검증
포지션 관리
Bybit 상태 동기화
수동 개입 감지 및 반영
거래 로그 저장
실시간 상태 publish
Backend 명령 수신
```

---

## 6.2 Bot Engine 내부 모듈

Bot Engine은 다음 모듈로 분리한다.

```text
BotRuntime
BotStateMachine
CommandConsumer
RuntimeState
ExchangeGateway
ReconciliationManager
ManualInterventionHandler
PaperExecutionEngine
UniverseManager
SymbolScanner
MarketDataCollector
CandleStore
IndicatorEngine
StrategyRegistry
StrategyModule
SignalEngine
EntryTimingEngine
RiskManager
OrderManager
PositionManager
PositionProtectionManager
TradeLogger
StatePublisher
```

---

### 6.3 BotRuntime

BotRuntime은 Bot Engine 전체 생명주기를 관리한다.

역할:

```text
설정 로드
runtime lock 획득
BotStateMachine 초기화
각 모듈 초기화
heartbeat 시작
graceful shutdown 처리
PAPER / LIVE 모드 초기화
```

BotRuntime은 프로그램 시작 시 자동으로 매매를 시작하지 않는다.

```text
BOOTING
→ 초기화 완료
→ STANDBY
```

---

### 6.4 BotStateMachine

BotStateMachine은 Bot Engine의 실행 상태를 관리한다.

상태:

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
```

주요 원칙:

```text
STANDBY에서는 신규 진입 금지
RUNNING에서만 신규 진입 가능
RECONCILING에서는 신규 진입 금지
ORDER_LOCKED에서는 신규 진입 금지
EMERGENCY_STOP에서는 신규 진입 금지
```

---

### 6.5 CommandConsumer

Backend API가 Redis Command Queue에 넣은 명령을 수신한다.

처리 명령:

```text
START_BOT
STOP_BOT
PAUSE_TRADING
RESUME_TRADING
RELOAD_CONFIG
CLOSE_POSITION
CANCEL_ORDER
SYNC_NOW
```

CommandConsumer는 명령을 직접 실행하지 않고 BotStateMachine 또는 적절한 내부 모듈에 전달한다.

---

### 6.6 ExchangeGateway

Bybit API 접근을 추상화하는 모듈이다.

역할:

```text
Bybit REST API 호출
Bybit WebSocket 연결
시장 데이터 구독
주문 생성
주문 취소
잔고 조회
포지션 조회
미체결 주문 조회
체결 이벤트 수신
TP/SL 설정
TP/SL 상태 조회
레버리지 설정
```

중요 원칙:

```text
Bot Engine 내부 다른 모듈은 Bybit SDK를 직접 호출하지 않는다.
모든 거래소 접근은 ExchangeGateway를 통해 수행한다.
```

---

### 6.7 ReconciliationManager

ReconciliationManager는 Bybit 실제 상태와 Bot 내부 상태를 동기화한다.

역할:

```text
Bybit 포지션 조회
Bybit 미체결 주문 조회
Bybit 체결 상태 조회
Bybit TP/SL 상태 조회
내부 PositionRegistry와 비교
내부 OrderRegistry와 비교
차이 감지
내부 상태 보정
동기화 이벤트 저장
```

동기화 기준:

```text
Bybit 실제 상태 = 최종 진실
```

동기화 타이밍:

```text
프로그램 시작 시
START 명령 이후 SYNCING 상태
주기적 동기화
주문 이벤트 직후
WebSocket 재연결 후
order timeout 이후
수동 SYNC_NOW 명령 수신 시
```

---

### 6.8 ManualInterventionHandler

ManualInterventionHandler는 Bybit 앱 또는 외부 경로에서 발생한 수동 개입을 감지하고 내부 상태에 반영한다.

수동 개입 예시:

```text
Bybit 앱에서 신규 포지션 생성
Bybit 앱에서 기존 포지션 수량 증가
Bybit 앱에서 기존 포지션 수량 감소
Bybit 앱에서 포지션 청산
Bybit 앱에서 미체결 주문 생성
Bybit 앱에서 주문 취소
```

처리 원칙:

```text
수동 개입을 신규 전략 신호로 간주하지 않는다.
Bybit 실제 수량을 내부 상태에 반영한다.
신규 진입을 일정 시간 중지한다.
수동 증가분은 manual_added_qty로 기록한다.
평균 진입가는 Bybit avgPrice 기준으로 보정한다.
TP/SL 보호 상태를 재검증한다.
```

기존 봇 포지션 수량이 수동으로 증가한 경우:

```text
Bybit 실제 수량을 내부 position_qty에 반영
manual_added_qty에 증가분 기록
avg_entry_price를 Bybit avgPrice로 보정
TP/SL이 전체 수량 기준으로 적용되어 있는지 재검증
필요 시 PositionProtectionManager에 TP/SL 재동기화 요청
```

---

### 6.9 PaperExecutionEngine

PaperExecutionEngine은 PAPER 모드에서 가상 주문과 가상 체결을 담당한다.

역할:

```text
실제 Bybit 시장 데이터 기반 가상 시장가 체결
가상 잔고 관리
가상 포지션 생성
가상 수수료 반영
가상 슬리피지 반영
가상 TP/SL 가격 저장
가상 청산 이벤트 생성
```

PAPER 모드 원칙:

```text
실제 Bybit API로 주문하지 않는다.
모든 주문은 시장가 체결 시뮬레이션으로 처리한다.
LIMIT / AGGRESSIVE_LIMIT 대기열 시뮬레이션은 하지 않는다.
전략, 리스크, 포지션 관리 흐름은 LIVE와 동일하게 유지한다.
```

---

### 6.10 UniverseManager

거래 가능한 전체 종목 universe를 관리한다.

역할:

```text
Bybit USDT Perpetual 종목 목록 조회
거래 가능 상태 확인
상장 폐지/거래 정지 종목 제외
최소 주문 수량/가격 단위/수량 단위 관리
종목별 메타데이터 캐싱
```

UniverseManager는 진입 판단을 하지 않는다.

---

### 6.11 SymbolScanner

전략별 감시 후보 코인을 선정한다.

역할:

```text
전체 universe에서 감시 후보 선정
거래량 필터
스프레드 필터
ATR 필터
상장일/거래 상태 필터
전략별 candidate list 생성
```

SymbolScanner는 다음을 수행하지 않는다.

```text
롱/숏 최종 판단
주문 실행
리스크 승인
포지션 관리
```

---

### 6.12 MarketDataCollector

실시간 시장 데이터를 수집한다.

역할:

```text
ticker 수신
kline 수신
orderbook 수신
최근 체결 데이터 수신
WebSocket 재연결
시장 데이터 누락 감지
```

---

### 6.13 CandleStore

캔들 데이터를 메모리와 저장소에 관리한다.

역할:

```text
1m/5m/15m 등 timeframe별 캔들 저장
완성 캔들/진행 중 캔들 구분
지표 계산용 캔들 제공
재시작 시 최근 캔들 복구
```

---

### 6.14 IndicatorEngine

캔들을 기반으로 지표를 계산한다.

역할:

```text
EMA
RSI
ATR
Volume Ratio
Price Distance
Swing High/Low
기타 전략 필요 지표
```

IndicatorEngine은 매매 판단을 하지 않고 지표 snapshot만 생성한다.

---

### 6.15 StrategyRegistry

활성 전략 목록을 관리한다.

역할:

```text
활성화된 전략 등록
전략별 설정 로드
전략별 감시 timeframe 제공
전략별 필요 지표 선언
전략 모듈 실행 관리
```

v1에서는 Trend Following Strategy만 등록한다.

향후 Range Strategy 같은 전략을 AddOn으로 추가할 수 있다.

---

### 6.16 StrategyModule

전략별 조건을 평가한다.

v1 전략:

```text
Trend Following Strategy
```

역할:

```text
추세 방향 후보 판단
롱 후보 신호 생성
숏 후보 신호 생성
청산 후보 신호 생성
신호 사유 생성
```

수행하지 않는 것:

```text
주문 실행
리스크 최종 승인
포지션 수량 최종 결정
거래소 API 호출
```

---

### 6.17 SignalEngine

여러 StrategyModule의 출력을 표준 Signal로 통합한다.

역할:

```text
전략별 signal 수집
중복 signal 정리
우선순위 처리
표준 Signal 객체 생성
EntryTimingEngine으로 전달
```

---

### 6.18 EntryTimingEngine

Signal 후보가 실제 진입 가능한 타이밍인지 판단한다.

역할:

```text
Pre-Breakout Scout 판단
Breakout Confirm 판단
Retest Confirm 판단
Anti-Chase 필터
진입 대기 상태 관리
entry mode 결정
```

EntryTimingEngine은 주문하지 않는다.

---

### 6.19 RiskManager

RiskManager는 실제 주문 전 최종 승인자다.

역할:

```text
거래 허용 여부 판단
포지션 크기 계산
레버리지 제한
일일 손실 제한 확인
동시 포지션 수 제한
종목별 노출 제한
전체 계좌 리스크 제한
PAPER 가상 잔고 기준 리스크 계산
LIVE 실제 계좌 기준 리스크 계산
```

RiskManager가 거절하면 주문은 실행되지 않는다.

---

### 6.20 OrderManager

OrderManager는 LIVE 모드에서 RiskManager가 승인한 실제 주문만 실행한다.

역할:

```text
지정가 주문
aggressive limit 주문
reduce-only 주문
주문 취소
주문 상태 확인
주문 실패 처리
부분 체결 처리
client_order_id 기반 멱등성 처리
```

OrderManager는 전략 판단을 하지 않는다.

PAPER 모드에서는 OrderManager가 실제 주문을 실행하지 않고 PaperExecutionEngine으로 위임한다.

---

### 6.21 PositionManager

PositionManager는 보유 포지션의 생명주기를 관리한다.

역할:

```text
현재 포지션 상태 관리
평균 진입가 관리
수량 관리
수동 증가분 manual_added_qty 관리
부분익절 관리
트레일링 스탑 관리
시간 손절 관리
시나리오 무효화 청산 관리
거래소 포지션과 내부 상태 동기화
```

청산 주문은 LIVE에서는 OrderManager를 통해 실행한다.

PAPER에서는 PaperExecutionEngine을 통해 가상 청산한다.

---

### 6.22 PositionProtectionManager

PositionProtectionManager는 LIVE 포지션의 TP/SL 보호 설정과 검증을 담당한다.

역할:

```text
진입 체결 후 TP/SL 설정 요청
Bybit Set Trading Stop 호출
TP/SL 설정 재조회
TP/SL 보호 상태 검증
수동 수량 증가 후 TP/SL 전체 수량 적용 여부 확인
TP/SL 불일치 시 재동기화 요청
TP/SL 실패 시 emergency close 요청
```

PositionProtectionManager는 직접 Bybit SDK를 호출하지 않고 ExchangeGateway를 통해 TP/SL을 설정한다.

---

### 6.23 TradeLogger

매매 관련 이벤트를 PostgreSQL에 저장한다.

역할:

```text
신호 기록
주문 기록
체결 기록
포지션 변화 기록
청산 사유 기록
PnL 기록
봇 이벤트 기록
명령 처리 결과 기록
reconciliation 기록
manual intervention 기록
TP/SL 설정/검증 기록
```

---

### 6.24 StatePublisher

Bot Engine의 실시간 상태를 Redis에 publish한다.

역할:

```text
heartbeat 갱신
현재 봇 상태 publish
PAPER / LIVE 모드 publish
현재 포지션 publish
EXTERNAL / MANUAL_ADDED 상태 publish
실시간 PnL publish
리스크 상태 publish
TP/SL 보호 상태 publish
최근 이벤트 publish
reconciliation 상태 publish
```

---

## 7. PostgreSQL

PostgreSQL은 영구 데이터 저장소다.

저장 대상:

```text
trades
orders
fills
positions
signals
bot_events
strategy_configs
command_logs
daily_pnl
reconciliation_logs
manual_intervention_logs
position_protection_logs
paper_account_snapshots
```

저장 원칙:

```text
재시작 후 복구가 필요한 데이터는 PostgreSQL에 저장한다.
감사 추적이 필요한 이벤트는 PostgreSQL에 저장한다.
전략 분석에 필요한 이벤트는 PostgreSQL에 저장한다.
수동 개입 이벤트는 PostgreSQL에 저장한다.
TP/SL 설정 및 실패 이벤트는 PostgreSQL에 저장한다.
```

---

## 8. Redis

Redis는 실시간 상태 공유와 명령 전달에 사용한다.

사용 대상:

```text
bot:status
bot:mode
bot:heartbeat
bot:risk_status
bot:positions
bot:pnl
bot:protection_status
bot:reconciliation_status
commands:bot
events:bot
lock:quantbot:live
```

Redis 역할:

```text
Bot runtime lock
Command Queue
Dashboard 실시간 상태
Heartbeat
Pub/Sub
짧은 수명 이벤트 스트림
```

Redis에만 의존하면 안 되는 데이터:

```text
거래 기록
체결 기록
포지션 이력
수동 개입 이력
TP/SL 실패 이력
명령 감사 로그
```

이 데이터는 PostgreSQL에도 저장한다.

---

## 9. Bybit API / WebSocket

Bybit 접근은 Bot Engine의 ExchangeGateway만 수행한다.

```text
Frontend Dashboard
→ Bybit 직접 접근 금지

Backend API
→ Bybit 직접 주문 금지

Bot Engine / ExchangeGateway
→ Bybit 접근 담당
```

ExchangeGateway가 담당하는 Bybit 기능:

```text
시장 데이터 조회
WebSocket 구독
포지션 조회
미체결 주문 조회
잔고 조회
주문 생성
주문 취소
레버리지 설정
TP/SL 설정
TP/SL 상태 조회
체결 이벤트 수신
```

---

## 10. 서비스 간 데이터 흐름

### 10.1 프로그램 시작 흐름

```text
Bot Process Start
→ BotRuntime
→ Config Load
→ Runtime Lock 획득
→ Module Init
→ BotStateMachine: BOOTING
→ 기본 동기화
→ BotStateMachine: STANDBY
```

자동으로 RUNNING 상태가 되면 안 된다.

---

### 10.2 사용자 START 흐름

```text
Frontend Dashboard START 클릭
→ Backend API
→ Command Log 저장
→ Redis Command Queue: START_BOT
→ CommandConsumer
→ BotStateMachine: START_REQUESTED
→ ReconciliationManager: SYNCING
→ 상태 검증 완료
→ BotStateMachine: READY
→ BotStateMachine: RUNNING
```

---

### 10.3 시장 데이터 흐름

```text
Bybit WebSocket
→ ExchangeGateway
→ MarketDataCollector
→ CandleStore
→ IndicatorEngine
→ StrategyModule
→ SignalEngine
→ EntryTimingEngine
→ RiskManager
→ OrderManager or PaperExecutionEngine
```

---

### 10.4 LIVE 주문 흐름

```text
EntrySignal
→ RiskManager
→ OrderManager
→ ExchangeGateway
→ Bybit Order API
→ 체결 확인
→ PositionManager
→ PositionProtectionManager
→ ExchangeGateway
→ Bybit TP/SL API
→ TP/SL 검증
→ Position ACTIVE
→ TradeLogger
→ StatePublisher
```

---

### 10.5 PAPER 주문 흐름

```text
EntrySignal
→ RiskManager
→ PaperExecutionEngine
→ 가상 시장가 체결
→ 가상 포지션 생성
→ 가상 TP/SL 가격 저장
→ PositionManager
→ TradeLogger
→ StatePublisher
```

---

### 10.6 Bybit 동기화 흐름

```text
ReconciliationManager
→ ExchangeGateway
→ Bybit positions / open orders / TP/SL 조회
→ 내부 PositionRegistry / OrderRegistry와 비교
→ 차이 감지
→ 내부 상태 보정
→ ManualInterventionHandler 필요 시 호출
→ TradeLogger
→ StatePublisher
```

---

### 10.7 수동 수량 증가 흐름

```text
사용자가 Bybit 앱에서 기존 봇 포지션 수량 증가
→ ReconciliationManager가 Bybit 수량 변화 감지
→ ManualInterventionHandler
→ 내부 position_qty를 Bybit 실제 수량으로 보정
→ manual_added_qty 기록
→ avg_entry_price를 Bybit avgPrice로 보정
→ PositionProtectionManager가 TP/SL 전체 수량 보호 상태 재검증
→ 필요 시 TP/SL 재동기화
→ 신규 진입 일시 중지
→ TradeLogger
→ StatePublisher
```

---

### 10.8 실시간 상태 흐름

```text
Bot Engine
→ StatePublisher
→ Redis
→ Backend API
→ WebSocket
→ Frontend Dashboard
```

---

## 11. Monorepo 구조

```text
quantbot/
  apps/
    api/
      main.py
      routers/
      schemas/
      services/

    bot/
      main.py
      runtime/
        bot_runtime.py
        bot_state_machine.py
        lifecycle.py
        heartbeat.py
      workers/

    frontend/
      src/
      package.json

  packages/
    core/
      models/
      enums/
      errors/

    exchange/
      gateway.py
      bybit_gateway.py

    universe/
      universe_manager.py
      symbol_meta.py

    scanner/
      symbol_scanner.py

    market_data/
      collector.py
      candle_store.py

    indicators/
      indicator_engine.py

    strategy/
      registry.py
      base.py
      trend_following.py

    signal/
      signal_engine.py

    entry/
      entry_timing_engine.py
      anti_chase.py
      retest.py

    risk/
      risk_manager.py
      position_sizing.py
      leverage.py

    execution/
      order_manager.py
      order_policy.py
      paper_execution_engine.py

    position/
      position_manager.py
      protection_manager.py

    reconciliation/
      reconciliation_manager.py
      manual_intervention_handler.py

    storage/
      database.py
      repositories/

    messaging/
      redis_client.py
      command_queue.py
      event_bus.py

    config/
      settings.py
```

---

## 12. 책임 분리 요약

```text
Frontend Dashboard
= UI와 사용자 명령 요청

Backend API
= 조회, 설정, 명령 생성, WebSocket

BotRuntime
= Bot Engine 생명주기 관리

BotStateMachine
= STANDBY/RUNNING/PAUSED/EMERGENCY_STOP 등 상태 관리

Bot Engine
= 시장 데이터, 전략 판단, 리스크, 주문, 포지션 관리, Bybit 동기화

ExchangeGateway
= Bybit API 접근 추상화

ReconciliationManager
= Bybit 실제 상태와 내부 상태 동기화

ManualInterventionHandler
= Bybit 앱 수동 개입 감지 및 내부 상태 반영

PaperExecutionEngine
= PAPER 모드 가상 시장가 체결

UniverseManager
= 거래 가능 종목 universe 관리

SymbolScanner
= 전략별 감시 후보 선정

StrategyModule
= 전략 조건 평가와 후보 신호 생성

EntryTimingEngine
= 실제 진입 타이밍 판단

RiskManager
= 주문 전 최종 리스크 승인

OrderManager
= LIVE 실제 주문 실행

PositionManager
= 보유 포지션 생명주기 관리

PositionProtectionManager
= LIVE TP/SL 설정 및 검증

PostgreSQL
= 영구 데이터 저장

Redis
= 실시간 상태, 명령 큐, 런타임 락
```

---

## 13. 최종 원칙

```text
Bot Engine은 Backend API와 분리한다.
Backend API는 직접 주문하지 않는다.
Bot Engine만 Bybit 주문 권한을 가진다.
거래소 접근은 ExchangeGateway를 통해서만 수행한다.
프로그램 시작만으로 매매를 시작하지 않는다.
STANDBY에서 START 명령을 받아야 RUNNING으로 전환된다.
PAPER는 실제 시장 데이터와 가상 시장가 체결을 사용한다.
LIVE는 실제 주문을 사용한다.
LIVE 신규 진입 후 TP/SL 설정과 검증은 필수다.
Bybit 실제 상태를 최종 진실로 사용한다.
수동 수량 증가는 내부 포지션 수량에 반영한다.
수동 증가분은 신규 전략 신호로 간주하지 않는다.
전략은 주문하지 않고 신호만 생성한다.
SymbolScanner는 코인 후보만 고른다.
EntryTimingEngine은 실제 진입 타이밍만 판단한다.
RiskManager가 승인하지 않은 주문은 실행하지 않는다.
OrderManager는 LIVE 승인 주문만 실행한다.
PaperExecutionEngine은 PAPER 가상 주문만 실행한다.
PositionManager는 진입 후 포지션 생명주기를 관리한다.
PositionProtectionManager는 TP/SL 보호를 관리한다.
전략은 AddOn 구조로 확장 가능하게 만든다.
v1에서는 Trend Following Strategy만 구현한다.
