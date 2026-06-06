"""BotRuntime: Bot Engine lifecycle orchestration (arch doc §6.3, §10.1, §10.2).

Responsibilities:
  * load config, connect Redis, build the exchange gateway
  * acquire the single-instance runtime lock (fail -> abort)
  * build the full module graph (market data, strategy, risk, execution, guards)
  * advance BOOTING -> STANDBY (never auto-RUNNING)
  * consume Backend commands and drive the state machine (START -> ... -> RUNNING)
  * run the command / reconciliation / heartbeat / trading loops
  * graceful shutdown (release lock)
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from apps.bot.runtime.bot_state_machine import BotStateMachine
from apps.bot.runtime.heartbeat import Heartbeat
from apps.bot.runtime.runtime_state import RuntimeState
from apps.bot.workers.trading_pipeline import (
    GuardSet,
    LiveExecutor,
    MarketContext,
    PaperExecutor,
    TradingService,
)
from packages.config.settings import AppConfig, Secrets
from packages.core.enums import BotMode, BotState, ExitReason
from packages.core.enums import OrderStatus
from packages.core.errors import RuntimeLockError
from packages.core.events import BotEvent, BotEventType
from packages.core.models import WalletBalance
from packages.entry import EntryTimingEngine
from packages.exchange import ExchangeGateway
from packages.execution import OrderManager, PaperExecutionEngine
from packages.guards import (
    ClockSyncGuard,
    DataQualityGuard,
    FundingGuard,
    GlobalKillSwitch,
    PreOrderCheck,
)
from packages.indicators import IndicatorEngine
from packages.market_data import CandleStore, MarketDataCollector
from packages.messaging import (
    Command,
    CommandQueue,
    CommandType,
    EventBus,
    RuntimeLock,
    StatePublisher,
    create_redis,
    state_keys,
)
from packages.pnl import compute_pnl, daily_loss_percent
from packages.position import (
    CooldownTracker,
    PositionManager,
    PositionProtectionManager,
)
from packages.reconciliation import (
    ManualInterventionHandler,
    ReconciliationManager,
)
from packages.risk import RiskManager
from packages.scanner import SymbolScanner
from packages.signal import SignalEngine
from packages.strategy import StrategyRegistry, TrendFollowingStrategy
from packages.universe import UniverseManager

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

class BotRuntime:
    def __init__(
        self,
        config: AppConfig,
        secrets: Secrets,
        *,
        redis: Any | None = None,
        gateway: ExchangeGateway | None = None,
        trade_logger: Any | None = None,
    ) -> None:
        self.config = config
        self.secrets = secrets
        self.state_machine = BotStateMachine()
        self.runtime_state = RuntimeState()

        self._redis = redis
        self._gateway = gateway
        self._trade_logger = trade_logger
        self._lock: RuntimeLock | None = None
        self._event_bus: EventBus | None = None
        self._commands: CommandQueue | None = None
        self._reconciler: ReconciliationManager | None = None
        self._heartbeat: Heartbeat | None = None
        self._state_publisher: StatePublisher | None = None

        # trading graph (built in startup)
        self._collector: MarketDataCollector | None = None
        self._universe: UniverseManager | None = None
        self._scanner: SymbolScanner | None = None
        self._indicators: IndicatorEngine | None = None
        self._risk_manager: RiskManager | None = None
        self._position_manager: PositionManager | None = None
        self._protection: PositionProtectionManager | None = None
        self._paper_engine: PaperExecutionEngine | None = None
        self._order_manager: OrderManager | None = None
        self._kill_switch: GlobalKillSwitch | None = None
        self._cooldown: CooldownTracker | None = None
        self._funding_guard: FundingGuard | None = None
        self._clock_guard: ClockSyncGuard | None = None
        self._trading: TradingService | None = None
        self._last_equity: Decimal = Decimal(str(config.paper.initial_balance_usdt))
        self._watchlist: list[str] = []
        self._last_scanner_refresh: float = 0.0
        self._scanner_atr_percent: dict[str, Decimal] = {}
        self._scanner_atr_updated_ms: dict[str, int] = {}
        self._scanner_snapshots_15m: dict[str, Any] = {}
        self._scanner_snapshots_5m: dict[str, Any] = {}
        self._scanner_cursor: int = 0
        self._last_reconciliation_status: dict[str, Any] = {}
        self._last_kill_switch_trip_reason: str | None = None

        self._shutdown = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------ #
    # construction helpers
    # ------------------------------------------------------------------ #
    def _build_gateway(self) -> ExchangeGateway:
        from packages.exchange.bybit_gateway import BybitExchangeGateway

        ex = self.config.exchange
        rl = self.config.api_rate_limit
        return BybitExchangeGateway(
            api_key=self.secrets.bybit_api_key,
            api_secret=self.secrets.bybit_api_secret,
            testnet=ex.use_testnet,
            category=self.config.bot.category,
            quote_coin=self.config.bot.quote_coin,
            recv_window=ex.recv_window,
            rest_rate_per_sec=rl.max_rest_requests_per_second,
            order_rate_per_sec=rl.max_order_requests_per_second,
            backoff_base_sec=rl.backoff_base_sec,
            backoff_max_sec=rl.backoff_max_sec,
        )

    def _build_trading(self) -> None:
        """Construct the full trading module graph + guards (arch doc §6.2)."""
        self._collector = MarketDataCollector(self._gateway, CandleStore())
        self._universe = UniverseManager(self._gateway, self.config.universe)
        self._scanner = SymbolScanner(
            self._universe,
            self.config.scanner,
            min_turnover_usdt=Decimal(str(self.config.universe.min_24h_turnover_usdt)),
        )
        self._indicators = IndicatorEngine()
        registry = StrategyRegistry()
        registry.register(TrendFollowingStrategy(self.config))
        self._risk_manager = RiskManager(self.config)
        self._position_manager = PositionManager(self.config)

        self._kill_switch = GlobalKillSwitch(self.config.global_kill_switch)
        self._cooldown = CooldownTracker(self.config.cooldown)
        self._funding_guard = FundingGuard(self.config.funding_guard)
        self._clock_guard = ClockSyncGuard(
            max_time_drift_ms=self.config.clock_sync.max_time_drift_ms,
            block_trading_if_drift_ms_above=self.config.clock_sync.block_trading_if_drift_ms_above,
        )
        guards = GuardSet(
            state_machine=self.state_machine,
            data_quality=DataQualityGuard(self.config.data_quality),
            pre_order_check=PreOrderCheck(self.config),
            kill_switch=self._kill_switch,
            cooldown=self._cooldown,
            funding_guard=self._funding_guard,
            clock_guard=self._clock_guard,
        )

        if self.config.bot.mode == BotMode.LIVE:
            self._order_manager = OrderManager(
                self._gateway,
                self.config,
                trade_logger=self._trade_logger,
                order_sink=self._register_order,
                pending_order_sink=self.runtime_state.reserve_order,
                pending_order_clear_sink=self.runtime_state.clear_order_reservation,
            )
            self._protection = PositionProtectionManager(
                self._gateway, self._order_manager, self._event_bus, self.config,
                trade_logger=self._trade_logger,
            )
            executor = LiveExecutor(self._gateway, self._order_manager)
        else:
            if self._paper_engine is None:
                self._paper_engine = PaperExecutionEngine(self.config)
            else:
                self._paper_engine.configure(self.config)
            executor = PaperExecutor(self._paper_engine)
            self._protection = None

        self._trading = TradingService(
            self.config,
            mode=self.config.bot.mode,
            signal_engine=SignalEngine(registry),
            entry_engine=EntryTimingEngine(self.config),
            risk_manager=self._risk_manager,
            position_manager=self._position_manager,
            state=self.runtime_state,
            executor=executor,
            guards=guards,
            protection_manager=self._protection,
            trade_logger=self._trade_logger,
            event_bus=self._event_bus,
        )

    def _build_reconciler(self) -> None:
        assert self._gateway is not None and self._event_bus is not None
        handler = ManualInterventionHandler(
            self.runtime_state,
            self._event_bus,
            self.config.manual_intervention,
            protection_resync=self._resync_protection,
            risk_exceeded_check=self._risk_exceeded,
            trade_logger=self._trade_logger,
        )
        self._reconciler = ReconciliationManager(
            self._gateway,
            self.runtime_state,
            handler,
            self._event_bus,
            self.config.reconciliation,
            trade_logger=self._trade_logger,
        )

    async def _resync_protection(self, position) -> bool:
        """Manual-intervention TP/SL resync hook (impl doc §4.4 step 8-10)."""
        if self._protection is None:  # PAPER: virtual TP/SL already on the position
            return True
        result = await self._protection.resync(position)
        return result.protected

    def _risk_exceeded(self, position) -> bool:
        """Best-effort per-symbol risk check after a manual qty increase (§4.4 note)."""
        if position.initial_risk_per_unit is None or self._last_equity <= 0:
            return False
        risk_pct = position.initial_risk_per_unit * position.qty / self._last_equity * Decimal(100)
        return risk_pct > Decimal(str(self.config.risk.max_symbol_risk_percent))

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    async def startup(self) -> None:
        """BOOTING -> STANDBY with lock + initial reconcile (arch doc §10.1)."""
        logger.info("BotRuntime starting (mode=%s)", self.config.bot.mode)
        if self._redis is None:
            self._redis = create_redis(self.secrets.redis_url)
        if self._gateway is None:
            self._gateway = self._build_gateway()

        self._event_bus = EventBus(self._redis, sink=self._trade_logger)
        self._commands = CommandQueue(self._redis)
        self._state_publisher = StatePublisher(
            self._redis,
            self.config.bot.mode,
            require_sl=self.config.tpsl.use_exchange_sl,
            require_tp=self.config.tpsl.use_exchange_tp,
        )
        self._lock = RuntimeLock(
            self._redis, ttl_sec=max(10, self.config.bot.heartbeat_interval_sec * 4)
        )

        self._build_trading()  # market data, strategy, risk, execution, guards

        self._build_reconciler()
        self._heartbeat = Heartbeat(
            self._redis, self._lock, self.state_machine, self.config.bot.mode
        )

        if not await self._lock.acquire():
            raise RuntimeLockError(
                "Another Bot Engine instance holds lock:quantbot:live"
            )

        await self._redis.set(state_keys.BOT_MODE, self.config.bot.mode.value)
        if self._universe is not None:
            await self._universe.refresh()

        if self.config.reconciliation.run_on_startup:
            result = await self._reconciler.reconcile_once()
            self._record_reconciliation_risk(result)

        self.state_machine.transition(BotState.STANDBY, reason="boot complete")
        await self._heartbeat.beat_once()
        logger.info("BotRuntime in STANDBY; awaiting START command")

    def _register_order(self, order) -> None:
        key = order.client_order_id or order.order_id
        if key:
            self.runtime_state.orders[key] = order
            self.runtime_state.clear_order_reservation(order.client_order_id)

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        await self.startup()
        self._tasks = [
            asyncio.create_task(self._command_loop(), name="command_loop"),
            asyncio.create_task(self._reconciliation_loop(), name="reconcile_loop"),
            asyncio.create_task(self._heartbeat_loop(), name="heartbeat_loop"),
            asyncio.create_task(self._trading_loop(), name="trading_loop"),
            asyncio.create_task(self._pnl_loop(), name="pnl_loop"),
            asyncio.create_task(self._clock_loop(), name="clock_loop"),
        ]
        self._start_market_ws()
        self._start_private_ws()
        await self._shutdown.wait()
        await self.shutdown()

    def request_shutdown(self) -> None:
        self._shutdown.set()

    async def shutdown(self) -> None:
        logger.info("BotRuntime shutting down")
        if not self.state_machine.is_terminal():
            try:
                self.state_machine.transition(BotState.STOPPING, reason="shutdown")
            except Exception:
                self.state_machine.force(BotState.STOPPING, reason="shutdown")
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self._lock is not None:
            await self._lock.release()
        self.state_machine.force(BotState.STOPPED, reason="shutdown complete")

    # ------------------------------------------------------------------ #
    # workers
    # ------------------------------------------------------------------ #
    async def _command_loop(self) -> None:
        assert self._commands is not None
        while not self._shutdown.is_set():
            try:
                cmd = await self._commands.consume(timeout=1.0)
            except Exception:
                logger.exception("command consume failed")
                await asyncio.sleep(1.0)
                continue
            if cmd is not None:
                await self.handle_command(cmd)

    async def _reconciliation_loop(self) -> None:
        assert self._reconciler is not None
        while not self._shutdown.is_set():
            interval = self._reconciler.next_interval_sec()
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=interval)
                return  # shutdown requested
            except asyncio.TimeoutError:
                pass
            if self.state_machine.state in (
                BotState.RUNNING,
                BotState.PAUSED,
                BotState.STANDBY,
                BotState.RISK_LOCKED,
            ):
                try:
                    result = await self._reconciler.reconcile_once()
                    self._record_reconciliation_risk(result)
                    await self._apply_kill_switch_trip()
                except Exception:
                    logger.exception("reconciliation cycle failed")

    async def _heartbeat_loop(self) -> None:
        assert self._heartbeat is not None
        interval = self.config.bot.heartbeat_interval_sec
        while not self._shutdown.is_set():
            try:
                await self._heartbeat.beat_once()
                await self._publish_state()
            except Exception:
                logger.exception("heartbeat failed")
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=interval)
                return
            except asyncio.TimeoutError:
                pass

    async def _equity_snapshot(self, marks: dict[str, Decimal]) -> Decimal:
        """Account equity for the dashboard: LIVE Bybit wallet or PAPER virtual wallet.

        Without this, ``bot:pnl`` has no equity and the dashboard shows "-" in LIVE
        (the PAPER snapshot table it otherwise falls back to is empty in LIVE).
        """
        if self.config.bot.mode == BotMode.LIVE:
            try:
                return (await self._gateway.get_wallet_balance()).equity
            except Exception:
                logger.debug("wallet balance fetch failed; using last equity")
                return self._last_equity
        if self._paper_engine is not None:
            return self._paper_engine.wallet(marks).equity
        return self._last_equity

    async def _wallet_snapshot(self, marks: dict[str, Decimal]) -> WalletBalance:
        if self.config.bot.mode == BotMode.LIVE:
            try:
                return await self._gateway.get_wallet_balance()
            except Exception:
                logger.debug("wallet balance fetch failed; using last equity")
        elif self._paper_engine is not None:
            return self._paper_engine.wallet(marks)
        return WalletBalance(
            coin=self.config.bot.account_currency,
            equity=self._last_equity,
            available_balance=self._last_equity,
            wallet_balance=self._last_equity,
            unrealized_pnl=Decimal(0),
        )

    async def _publish_state(self) -> None:
        if self._state_publisher is None:
            return
        positions = self.runtime_state.open_positions()
        snap = compute_pnl(self.runtime_state.active_bot_positions(), {})
        await self._state_publisher.publish(
            state=self.state_machine.state,
            positions=positions,
            pnl={
                "realized": str(snap.realized),
                "unrealized": str(snap.unrealized),
                "fees": str(snap.fees),
                "net": str(snap.net),
                "equity": str(self._last_equity),
            },
            risk_status=self._risk_status(),
            protection_status=self._protection_status(),
            reconciliation_status=self._last_reconciliation_status,
        )

    # ------------------------------------------------------------------ #
    # PnL loop (impl doc §18: 10s flat / 3s with position)
    # ------------------------------------------------------------------ #
    async def _pnl_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                await self._publish_and_persist_pnl()
            except Exception:
                logger.exception("pnl loop failed")
            interval = 3 if self.runtime_state.has_open_bot_position() else 10
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=interval)
                return
            except asyncio.TimeoutError:
                pass

    async def _publish_and_persist_pnl(self) -> None:
        marks: dict[str, Decimal] = {}
        if self._collector is not None:
            marks = {t.symbol: t.last_price for t in self._collector.tickers()}
        positions = list(self.runtime_state.positions.values())
        snap = compute_pnl(positions, marks)
        open_positions = self.runtime_state.open_positions()
        wallet = await self._wallet_snapshot(marks)
        equity = wallet.equity
        self._last_equity = equity
        pnl_payload = {
            "realized": str(snap.realized),
            "unrealized": str(wallet.unrealized_pnl),
            "fees": str(snap.fees),
            "funding_fees": str(snap.funding),
            "net": str(snap.net),
            "equity": str(equity),
            "wallet_balance": str(wallet.wallet_balance),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if self._trade_logger is not None:
            day = datetime.now(KST).strftime("%Y-%m-%d")
            account = await self._trade_logger.log_account_equity(
                day=day,
                mode=self.config.bot.mode.value,
                equity=str(equity),
                wallet_balance=str(wallet.wallet_balance),
                unrealized_pnl=str(wallet.unrealized_pnl),
                realized_pnl=str(snap.realized),
                fees=str(snap.fees),
                funding_fees=str(snap.funding),
            )
            pnl_payload.update(
                {
                    "day": account["day"],
                    "start_equity": account["start_equity"],
                    "daily_net_pnl": account["net_pnl"],
                    "daily_net_pnl_percent": account["net_pnl_percent"],
                    "max_drawdown_today": account["max_drawdown_percent"],
                    "updated_at": account["updated_at"],
                }
            )
        if self._state_publisher is not None:
            await self._state_publisher.publish(
                state=self.state_machine.state,
                positions=open_positions,
                pnl=pnl_payload,
                risk_status=self._risk_status(),
                protection_status=self._protection_status(),
                reconciliation_status=self._last_reconciliation_status,
            )
        if self._trade_logger is not None:
            day = datetime.now(KST).strftime("%Y-%m-%d")
            await self._trade_logger.log_daily_pnl(
                day=day, realized=str(snap.realized),
                unrealized=str(wallet.unrealized_pnl),
                fees=str(snap.fees),
                net=str(pnl_payload.get("daily_net_pnl", snap.net)),
            )
            if self._paper_engine is not None:
                await self._trade_logger.log_paper_snapshot(
                    equity=str(wallet.equity), balance=str(wallet.wallet_balance),
                    unrealized_pnl=str(wallet.unrealized_pnl),
                )
        if self._kill_switch is not None and self._last_equity > 0:
            daily_net = Decimal(str(pnl_payload.get("daily_net_pnl", snap.net)))
            daily_snapshot = snap.__class__(
                realized=daily_net,
                unrealized=Decimal(0),
                fees=Decimal(0),
                funding=Decimal(0),
                net=daily_net,
            )
            loss = max(Decimal(0), daily_loss_percent(daily_snapshot, self._last_equity))
            self._kill_switch.update_pnl(
                daily_loss_percent=float(loss),
                intraday_drawdown_percent=float(loss),
            )
            await self._apply_kill_switch_trip()

    # ------------------------------------------------------------------ #
    # clock sync loop (impl doc §7 clock_sync)
    # ------------------------------------------------------------------ #
    async def _clock_loop(self) -> None:
        get_time = getattr(self._gateway, "get_server_time", None)
        interval = self.config.clock_sync.sync_interval_sec
        while not self._shutdown.is_set():
            if get_time is not None and self._clock_guard is not None:
                try:
                    self._clock_guard.update(await get_time())
                except Exception:
                    logger.debug("clock sync fetch failed")
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=interval)
                return
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------ #
    # WebSocket disconnect policy (impl doc §17.2)
    # ------------------------------------------------------------------ #
    async def _handle_ws_disconnect(self, *, private: bool = False) -> None:
        """Pause entries, REST-refresh, reconcile, then return to RUNNING (§17.2)."""
        await self._emit_event(
            BotEventType.NEW_ENTRIES_PAUSED,
            f"WebSocket disconnect ({'private' if private else 'public'})",
        )
        if self._kill_switch is not None:
            self._kill_switch.record_ws_disconnect()
            await self._apply_kill_switch_trip()
        was_running = self.state_machine.state == BotState.RUNNING
        if was_running:
            self.state_machine.transition(BotState.RECONCILING, reason="ws disconnect")
        if self._collector is not None:
            try:
                await self._collector.refresh_tickers()
            except Exception:
                logger.debug("REST ticker refresh failed during ws recovery")
        if self._reconciler is not None and self.config.reconciliation.run_after_ws_reconnect:
            result = await self._reconciler.reconcile_once()
            self._record_reconciliation_risk(result)
        if was_running and self.state_machine.state == BotState.RECONCILING:
            self.state_machine.transition(BotState.RUNNING, reason="ws recovered")

    async def _emit_event(self, event_type: BotEventType, message: str) -> None:
        if self._event_bus is not None:
            await self._event_bus.publish(BotEvent(type=event_type, message=message))

    def _start_market_ws(self) -> None:
        """Best-effort live WebSocket subscription (no-op if unsupported)."""
        start = getattr(self._gateway, "start_market_websocket", None)
        if start is None or self._collector is None:
            return
        try:
            start(
                symbols=self._watch_symbols(),
                on_candle=self._collector.store.update,
                on_ticker=self._collector.ingest_ticker,
                on_disconnect=lambda: asyncio.create_task(self._handle_ws_disconnect()),
            )
        except Exception:
            logger.warning("market WebSocket unavailable; using REST polling")

    def _start_private_ws(self) -> None:
        """Best-effort private WS: order/fill/position events trigger reconcile."""
        start = getattr(self._gateway, "start_private_websocket", None)
        if start is None:
            return
        try:
            start(
                on_order=lambda msg: self._schedule_private_event("order", msg),
                on_execution=lambda msg: self._schedule_private_event("execution", msg),
                on_position=lambda msg: self._schedule_private_event("position", msg),
                on_disconnect=lambda: self._schedule_ws_disconnect(private=True),
            )
        except Exception:
            logger.warning("private WebSocket unavailable; using REST reconciliation")

    def _schedule_private_event(self, kind: str, msg: dict) -> None:
        loop = self._loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.debug("private ws %s event dropped before runtime loop", kind)
                return

        def _create() -> None:
            asyncio.create_task(self._handle_private_event(kind, msg))

        loop.call_soon_threadsafe(_create)

    def _schedule_ws_disconnect(self, *, private: bool) -> None:
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(
            lambda: asyncio.create_task(self._handle_ws_disconnect(private=private))
        )

    async def _handle_private_event(self, kind: str, msg: dict) -> None:
        await self._emit_event(BotEventType.RECONCILED, f"private_ws:{kind}")
        if self._reconciler is not None:
            self._reconciler.mark_order_event()
            result = await self._reconciler.reconcile_once()
            self._record_reconciliation_risk(result)
            await self._apply_kill_switch_trip()

    # ------------------------------------------------------------------ #
    # trading loop (arch doc §10.3-10.5)
    # ------------------------------------------------------------------ #
    async def _trading_loop(self) -> None:
        """When RUNNING, scan candidates and run entry/management per symbol.

        Defensive: any missing data or per-symbol error is logged and skipped so
        one bad symbol never stalls the loop. Cadence ~ heartbeat interval.
        """
        interval = max(2, self.config.bot.heartbeat_interval_sec)
        while not self._shutdown.is_set():
            if self.state_machine.state == BotState.RUNNING:
                try:
                    await self._trading_cycle()
                except Exception:
                    logger.exception("trading cycle failed")
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=interval)
                return
            except asyncio.TimeoutError:
                pass

    async def _trading_cycle(self) -> None:
        assert self._trading is not None and self._collector is not None
        await self._collector.refresh_tickers()
        await self._refresh_watchlist_if_due()
        equity = await self._current_equity()
        self._last_equity = equity

        watch: list[dict] = []
        for symbol in self._watch_symbols():
            try:
                preview = await self._process_symbol(symbol, equity)
            except Exception:
                logger.exception("symbol %s processing failed", symbol)
                continue
            if preview is not None:
                watch.append(preview)
        await self._publish_watchlist(watch)

    async def _publish_watchlist(self, entries: list[dict]) -> None:
        if self._state_publisher is None:
            return
        try:
            await self._state_publisher.publish_watchlist(entries)
        except Exception:
            logger.debug("watchlist publish failed")

    def _watch_symbols(self) -> list[str]:
        if self._universe is None:
            return []
        symbols = self._watchlist
        # already-open bot positions are always watched (for management)
        held = [p.symbol for p in self.runtime_state.active_bot_positions()]
        watch = list(dict.fromkeys(held + symbols))
        return watch[: self.config.bot.max_symbols_to_watch]

    async def _refresh_watchlist_if_due(self, *, force: bool = False) -> None:
        if (
            self._universe is None
            or self._scanner is None
            or self._collector is None
            or self._indicators is None
        ):
            return
        now = time.monotonic()
        if (
            not force
            and self._last_scanner_refresh > 0
            and now - self._last_scanner_refresh < self.config.scanner.refresh_interval_sec
        ):
            return
        await self._universe.refresh()
        tickers = self._collector.tickers()
        if not tickers:
            tickers = await self._collector.refresh_tickers()
        candidates = self._scanner_prefilter_tickers(tickers)
        refresh_batch = self._scanner_refresh_batch(candidates)
        for ticker in refresh_batch:
            try:
                await self._collector.refresh_klines(
                    ticker.symbol,
                    "15",
                    limit=200,
                    min_refresh_ms=self.config.scanner.kline_15m_refresh_sec * 1000,
                )
                candles = self._collector.store.get(ticker.symbol, "15")
                snap = self._indicators.snapshot(ticker.symbol, "15", candles)
                if snap.atr_percent is not None:
                    self._scanner_atr_percent[ticker.symbol] = snap.atr_percent
                    self._scanner_atr_updated_ms[ticker.symbol] = int(time.time() * 1000)
                    self._scanner_snapshots_15m[ticker.symbol] = snap
                await self._collector.refresh_klines(
                    ticker.symbol,
                    "5",
                    limit=200,
                    min_refresh_ms=self.config.scanner.kline_5m_refresh_sec * 1000,
                )
                candles_5m = self._collector.store.get(ticker.symbol, "5")
                self._scanner_snapshots_5m[ticker.symbol] = self._indicators.snapshot(
                    ticker.symbol, "5", candles_5m
                )
            except Exception:
                logger.debug("scanner indicator refresh failed for %s", ticker.symbol)
        self._watchlist = self._scanner.scan(
            tickers,
            self._fresh_scanner_atr(candidates, int(time.time() * 1000)),
            snapshots_15m=self._scanner_snapshots_15m,
            snapshots_5m=self._scanner_snapshots_5m,
        )
        self._last_scanner_refresh = now

    def _scanner_prefilter_tickers(self, tickers) -> list:
        assert self._universe is not None
        cfg = self.config
        eligible = []
        for ticker in tickers:
            if not self._universe.is_tradable(ticker.symbol):
                continue
            if ticker.turnover_24h < Decimal(str(cfg.universe.min_24h_turnover_usdt)):
                continue
            if ticker.bid_price <= 0 or ticker.ask_price <= 0:
                continue
            mid = (ticker.bid_price + ticker.ask_price) / Decimal(2)
            if mid <= 0:
                continue
            spread = (ticker.ask_price - ticker.bid_price) / mid * Decimal(100)
            if spread > Decimal(str(cfg.scanner.max_spread_percent)):
                continue
            eligible.append((ticker, spread))
        if eligible:
            min_turnover = min(t.turnover_24h for t, _ in eligible)
            max_turnover = max(t.turnover_24h for t, _ in eligible)
            eligible.sort(
                key=lambda item: self._scanner_prefilter_score(
                    item[0], item[1], min_turnover, max_turnover
                ),
                reverse=True,
            )
        limit = max(
            cfg.scanner.max_candidates,
            cfg.scanner.max_candidates * cfg.scanner.atr_prefilter_multiple,
        )
        return [t for t, _ in eligible[:limit]]

    @staticmethod
    def _scanner_prefilter_score(
        ticker,
        spread_percent: Decimal,
        min_turnover: Decimal,
        max_turnover: Decimal,
    ) -> Decimal:
        if max_turnover == min_turnover:
            turnover_score = Decimal(100)
        elif max_turnover > 0:
            turnover_score = (
                (ticker.turnover_24h - min_turnover)
                / (max_turnover - min_turnover)
                * Decimal(100)
            )
        else:
            turnover_score = Decimal(0)
        spread_score = Decimal(100) if spread_percent <= Decimal("0.05") else Decimal(70)
        return turnover_score * Decimal("0.70") + spread_score * Decimal("0.30")

    def _scanner_refresh_batch(self, candidates) -> list:
        if not candidates:
            return []
        budget = max(1, self.config.scanner.atr_refresh_budget)
        size = min(budget, len(candidates))
        start = self._scanner_cursor % len(candidates)
        batch = [candidates[(start + i) % len(candidates)] for i in range(size)]
        self._scanner_cursor = (start + size) % len(candidates)
        return batch

    def _fresh_scanner_atr(self, candidates, now_ms: int) -> dict[str, Decimal]:
        candidate_symbols = {t.symbol for t in candidates}
        ttl_ms = max(1, self.config.scanner.atr_cache_ttl_sec) * 1000
        for symbol in list(self._scanner_atr_percent):
            updated_ms = self._scanner_atr_updated_ms.get(symbol)
            if (
                symbol not in candidate_symbols
                or updated_ms is None
                or now_ms - updated_ms > ttl_ms
            ):
                self._scanner_atr_percent.pop(symbol, None)
                self._scanner_atr_updated_ms.pop(symbol, None)
                self._scanner_snapshots_15m.pop(symbol, None)
                self._scanner_snapshots_5m.pop(symbol, None)
        return dict(self._scanner_atr_percent)

    async def _process_symbol(self, symbol: str, equity: Decimal) -> dict | None:
        """Manage an open position or consider a new entry.

        Returns a read-only watch-list preview for symbols that are candidates
        (no open bot position), or None for symbols already held / lacking data.
        """
        assert self._collector is not None and self._indicators is not None
        ticker = self._collector.ticker(symbol)
        if ticker is None:
            return None
        for tf in ("1", "5", "15"):
            await self._collector.refresh_klines(
                symbol,
                tf,
                limit=200,
                min_refresh_ms=self._kline_min_refresh_ms(tf),
            )
        snapshots = {
            tf: self._indicators.snapshot(
                symbol, tf, self._collector.store.get(symbol, tf)
            )
            for tf in ("1", "5", "15")
        }
        s1 = snapshots["1"]

        now_ms = int(time.time() * 1000)
        last_ticker_ms = self._collector.last_ticker_ms()
        max_ticker_delay_ms = self.config.data_quality.max_ticker_delay_sec * 1000
        if last_ticker_ms is None or now_ms - last_ticker_ms > max_ticker_delay_ms:
            try:
                await self._collector.refresh_tickers()
                ticker = self._collector.ticker(symbol)
            except Exception:
                logger.debug("ticker refresh failed before processing %s", symbol)
            if ticker is None:
                return None
            now_ms = int(time.time() * 1000)
        bid, ask = ticker.bid_price, ticker.ask_price

        # manage an existing position first
        pos = self.runtime_state.get_position(symbol)
        if pos is not None and pos.is_bot_managed and pos.is_active:
            atr1 = s1.atr14 or Decimal(0)
            actions = await self._trading.manage(
                symbol=symbol, price=ticker.last_price, atr=atr1,
                best_bid=bid, best_ask=ask, snapshot_1m=snapshots["1"],
                snapshot_5m=snapshots["5"],
                candle_1m=self._collector.store.last_closed(symbol, "1"),
                volume_ratio=s1.volume_ratio,
                funding_rate=ticker.funding_rate,
            )
            if actions and self._reconciler is not None:
                self._reconciler.mark_order_event()  # exits => reconcile soon (§4.2)
            return None

        # otherwise consider a new entry
        market = MarketContext(
            now_ms=now_ms,
            last_kline_ms=self._collector.last_kline_ms(symbol, "1"),
            last_ticker_ms=self._collector.last_ticker_ms(),
            missing_candles=self._collector.missing_candles(symbol, "1"),
            ticker_price=ticker.last_price, kline_close=s1.close,
            symbol_status="Trading",
            next_funding_time_ms=ticker.next_funding_time_ms,
            funding_rate=ticker.funding_rate,
        )
        box_high = s1.swing_high or ticker.last_price
        box_low = s1.swing_low or ticker.last_price
        meta = self._universe.get(symbol) if self._universe else None
        if meta is None:
            return None

        async def load_orderbook():
            ob = await self._collector.refresh_orderbook(symbol)
            return ob, self._collector.last_orderbook_ms(symbol)

        opened = await self._trading.evaluate_entry(
            symbol=symbol, snapshots=snapshots,
            candles_1m=self._collector.store.get_with_current(symbol, "1"),
            box_high=box_high, box_low=box_low, symbol_meta=meta,
            equity=equity, entry_price=ticker.last_price, best_bid=bid, best_ask=ask,
            market=market, orderbook_provider=load_orderbook,
        )
        if opened is not None:
            if self._reconciler is not None:
                self._reconciler.mark_order_event()  # entry => reconcile soon (§4.2)
            return None  # now a position; shown in the positions panel
        # no entry this cycle -> publish a read-only preview for the dashboard
        return self._trading.preview_watch(
            symbol=symbol, snapshots=snapshots,
            box_high=box_high, box_low=box_low, last_price=ticker.last_price,
        )

    def _kline_min_refresh_ms(self, timeframe: str) -> int:
        if timeframe == "1":
            return self.config.scanner.kline_1m_refresh_sec * 1000
        if timeframe == "5":
            return self.config.scanner.kline_5m_refresh_sec * 1000
        if timeframe == "15":
            return self.config.scanner.kline_15m_refresh_sec * 1000
        return 60_000

    async def _current_equity(self) -> Decimal:
        if self.config.bot.mode == BotMode.LIVE:
            try:
                return (await self._gateway.get_wallet_balance()).equity
            except Exception:
                return self._last_equity
        if self._paper_engine is not None:
            return self._paper_engine.wallet().equity
        return self._last_equity

    # ------------------------------------------------------------------ #
    # command dispatch (arch doc §5.2, §10.2)
    # ------------------------------------------------------------------ #
    async def handle_command(self, cmd: Command) -> None:
        assert self._event_bus is not None
        await self._event_bus.publish(
            BotEvent(
                type=BotEventType.COMMAND_RECEIVED,
                message=cmd.type.value,
                data={"id": cmd.id, "payload": cmd.payload},
            )
        )
        if self._trade_logger is not None:
            try:
                await self._trade_logger.log_command(
                    command_id=cmd.id, type=cmd.type.value, payload=cmd.payload
                )
            except Exception:
                logger.exception("command_log persist failed")
        try:
            await self._dispatch(cmd)
        except Exception as exc:  # noqa: BLE001
            logger.exception("command %s failed", cmd.type)
            await self._event_bus.publish(
                BotEvent(
                    type=BotEventType.COMMAND_FAILED,
                    message=f"{cmd.type.value}: {exc}",
                    data={"id": cmd.id},
                )
            )

    async def _dispatch(self, cmd: Command) -> None:
        match cmd.type:
            case CommandType.START_BOT:
                await self._start_trading()
            case CommandType.STOP_BOT:
                await self._stop_bot(cmd.payload)
            case CommandType.PAUSE_TRADING:
                if self.state_machine.state == BotState.RUNNING:
                    self.state_machine.transition(BotState.PAUSED, reason="command")
            case CommandType.RESUME_TRADING:
                if self.state_machine.state == BotState.PAUSED:
                    self.state_machine.transition(BotState.RUNNING, reason="command")
            case CommandType.RELOAD_CONFIG:
                self._reload_config()
            case CommandType.SYNC_NOW:
                if self._reconciler is not None:
                    result = await self._reconciler.reconcile_once()
                    self._record_reconciliation_risk(result)
            case CommandType.CANCEL_ORDER:
                await self._cancel_order(cmd.payload)
            case CommandType.CLOSE_POSITION:
                await self._close_position(cmd.payload)

    async def _start_trading(self) -> None:
        """STANDBY -> START_REQUESTED -> SYNCING -> READY -> RUNNING (impl doc §3)."""
        if self.state_machine.state != BotState.STANDBY:
            logger.warning(
                "START ignored: state is %s, not STANDBY", self.state_machine.state
            )
            return
        self.state_machine.transition(BotState.START_REQUESTED, reason="START_BOT")
        self.state_machine.transition(BotState.SYNCING, reason="pre-start sync")
        if self._reconciler is not None:
            result = await self._reconciler.reconcile_once()
            self._record_reconciliation_risk(result)
        self.state_machine.transition(BotState.READY, reason="sync complete")
        self.state_machine.transition(BotState.RUNNING, reason="start confirmed")
        if self._heartbeat is not None:
            await self._heartbeat.beat_once()
        logger.info("Bot is RUNNING")

    def _reload_config(self) -> None:
        from packages.config import load_app_config

        self.config = load_app_config(self.secrets.quantbot_config)
        self._build_trading()
        self._build_reconciler()
        if self._heartbeat is not None and self._lock is not None:
            self._heartbeat = Heartbeat(
                self._redis, self._lock, self.state_machine, self.config.bot.mode
            )
        if self._state_publisher is not None:
            self._state_publisher = StatePublisher(
                self._redis,
                self.config.bot.mode,
                require_sl=self.config.tpsl.use_exchange_sl,
                require_tp=self.config.tpsl.use_exchange_tp,
            )
        logger.info("Config reloaded and runtime modules rebuilt")

    async def _stop_bot(self, payload: dict) -> None:
        """Apply STOP options before graceful shutdown (backend doc §10.2)."""
        if payload.get("cancel_open_orders", True):
            await self._cancel_open_orders()
        if payload.get("close_positions", False):
            await self._close_all_positions()
        self.request_shutdown()

    async def _cancel_open_orders(self) -> None:
        if self._gateway is None:
            return
        cancelable = {OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED, OrderStatus.UNKNOWN}
        for order in list(self.runtime_state.orders.values()):
            if order.source.value != "BOT" or order.status not in cancelable:
                continue
            try:
                await self._gateway.cancel_order(
                    order.symbol, order.order_id, order.client_order_id
                )
                order.status = OrderStatus.CANCELLED
                await self._persist_cancelled_order(
                    order_id=order.order_id,
                    client_order_id=order.client_order_id,
                )
            except Exception:
                logger.exception("failed to cancel open order %s", order.order_id)

    async def _close_all_positions(self) -> None:
        if self._trading is None or self._collector is None:
            return
        if not self.state_machine.can_manage_positions():
            logger.warning("STOP close_positions ignored in state %s", self.state_machine.state)
            return
        await self._collector.refresh_tickers()
        for pos in list(self.runtime_state.active_bot_positions()):
            ticker = self._collector.ticker(pos.symbol)
            if ticker is None:
                logger.warning("STOP close_positions skipped; no ticker for %s", pos.symbol)
                continue
            ok = await self._trading.close_position(
                pos.symbol,
                best_bid=ticker.bid_price,
                best_ask=ticker.ask_price,
                reason=ExitReason.MANUAL_CLOSE,
                close_percent=Decimal("100"),
            )
            if ok and self._reconciler is not None:
                self._reconciler.mark_order_event()

    async def _cancel_order(self, payload: dict) -> None:
        if self._gateway is None:
            return
        await self._gateway.cancel_order(
            symbol=payload["symbol"],
            order_id=payload.get("order_id"),
            client_order_id=payload.get("client_order_id"),
        )
        self._mark_runtime_order_cancelled(
            order_id=payload.get("order_id"),
            client_order_id=payload.get("client_order_id"),
        )
        await self._persist_cancelled_order(
            order_id=payload.get("order_id"),
            client_order_id=payload.get("client_order_id"),
        )

    def _mark_runtime_order_cancelled(
        self, *, order_id: str | None, client_order_id: str | None
    ) -> None:
        for order in self.runtime_state.orders.values():
            if (
                (order_id and order.order_id == order_id)
                or (client_order_id and order.client_order_id == client_order_id)
            ):
                order.status = OrderStatus.CANCELLED

    async def _persist_cancelled_order(
        self, *, order_id: str | None, client_order_id: str | None
    ) -> None:
        update = getattr(self._trade_logger, "update_order_status", None)
        if update is None:
            return
        try:
            await update(
                order_id=order_id,
                client_order_id=client_order_id,
                status=OrderStatus.CANCELLED.value,
            )
        except Exception:
            logger.exception("order cancel status persist failed")

    async def _close_position(self, payload: dict) -> None:
        if self._trading is None or self._collector is None:
            return
        symbol = payload["symbol"]
        if not self.state_machine.can_manage_positions():
            logger.warning("CLOSE_POSITION ignored in state %s", self.state_machine.state)
            return
        await self._collector.refresh_tickers()
        ticker = self._collector.ticker(symbol)
        if ticker is None:
            logger.warning("CLOSE_POSITION ignored; no ticker for %s", symbol)
            return
        ok = await self._trading.close_position(
            symbol,
            best_bid=ticker.bid_price,
            best_ask=ticker.ask_price,
            reason=ExitReason.MANUAL_CLOSE,
            close_percent=Decimal(str(payload.get("close_percent", 100))),
        )
        if ok and self._reconciler is not None:
            self._reconciler.mark_order_event()

    def _record_reconciliation_risk(self, result) -> None:
        self._last_reconciliation_status = {
            "external_positions": result.external_positions,
            "qty_mismatches": result.qty_mismatches,
            "external_closes": result.external_closes,
            "exchange_closes": result.exchange_closes,
            "external_orders": result.external_orders,
            "stale_bot_orders_cancelled": result.stale_bot_orders_cancelled,
            "persisted_positions_closed": result.persisted_positions_closed,
            "changed": result.changed,
            "ts_ms": int(time.time() * 1000),
        }
        if self._kill_switch is None:
            return
        if result.qty_mismatches or result.external_closes:
            self._kill_switch.record_position_mismatch()

    async def _apply_kill_switch_trip(self) -> None:
        if self._kill_switch is None:
            return
        reason = self._kill_switch.evaluate()
        if reason is None:
            return
        if reason != self._last_kill_switch_trip_reason:
            self._last_kill_switch_trip_reason = reason
            await self._emit_event(BotEventType.KILL_SWITCH_TRIPPED, reason)
        if self.state_machine.state == BotState.RUNNING:
            self.state_machine.transition(BotState.RISK_LOCKED, reason=reason)

    def _risk_status(self) -> dict:
        status = {
            "new_entries_paused": self.runtime_state.new_entries_paused(),
            "pause_remaining_sec": self.runtime_state.pause_remaining_sec(),
        }
        if self._kill_switch is not None:
            status["kill_switch"] = self._kill_switch.snapshot()
        return status

    def _protection_status(self) -> dict:
        positions = []
        for p in self.runtime_state.open_positions():
            positions.append(
                {
                    "symbol": p.symbol,
                    "source": p.source.value,
                    "status": p.status.value,
                    "has_stop_loss": p.stop_loss_price is not None,
                    "has_take_profit": p.take_profit_price is not None,
                    "protected": (
                        (
                            not self.config.tpsl.use_exchange_sl
                            or p.stop_loss_price is not None
                        )
                        and (
                            not self.config.tpsl.use_exchange_tp
                            or p.take_profit_price is not None
                        )
                    ),
                }
            )
        return {"positions": positions}
