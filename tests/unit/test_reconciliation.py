"""Tests for ReconciliationManager + ManualInterventionHandler (impl doc §4)."""

from decimal import Decimal

from apps.bot.runtime.runtime_state import RuntimeState
from packages.core.enums import (
    EntryMode,
    PositionSide,
    PositionSource,
    PositionStatus,
)
from packages.core.events import BotEventType
from packages.core.models import ExchangeOrder, ExchangePosition, Position
from packages.core.enums import OrderStatus, Side
from packages.messaging import EventBus
from packages.reconciliation import ManualInterventionHandler, ReconciliationManager
from tests.fakes import FakeGateway


class _PersistedPositionCleanupLogger:
    def __init__(self, closed: list[str]) -> None:
        self.closed = closed
        self.calls = []

    async def close_stale_open_position_snapshots(self, *, active_symbols, mode):
        self.calls.append((set(active_symbols), mode))
        return self.closed

    async def log_reconciliation(self, summary):
        self.summary = summary

    async def log_manual_intervention(self, symbol, kind, data):
        self.manual_intervention = (symbol, kind, data)


def _make(config, events, trade_logger=None):
    state = RuntimeState()
    bus = EventBus(redis=None, sink=events)
    handler = ManualInterventionHandler(
        state, bus, config.manual_intervention, trade_logger=trade_logger
    )
    gw = FakeGateway()
    recon = ReconciliationManager(
        gw, state, handler, bus, config.reconciliation, trade_logger=trade_logger
    )
    return state, gw, recon


def _bot_position(symbol="BTCUSDT", qty="1", avg="100"):
    return Position(
        symbol=symbol,
        side=PositionSide.LONG,
        status=PositionStatus.ACTIVE,
        source=PositionSource.BOT,
        qty=Decimal(qty),
        avg_entry_price=Decimal(avg),
        entry_mode=EntryMode.BREAKOUT_CONFIRM,
        signal_score=Decimal("7"),
        strategy_reason="trend long",
    )


async def test_external_position_adopted(config, events):
    state, gw, recon = _make(config, events)
    gw.set_position(
        ExchangePosition(
            symbol="ETHUSDT", side=PositionSide.SHORT,
            size=Decimal("2"), avg_price=Decimal("2000"),
        )
    )
    result = await recon.reconcile_once()
    assert "ETHUSDT" in result.external_positions
    adopted = state.get_position("ETHUSDT")
    assert adopted.source == PositionSource.EXTERNAL
    assert not adopted.is_bot_managed
    assert state.new_entries_paused()
    assert BotEventType.EXTERNAL_POSITION_DETECTED in events.types()


async def test_manual_add_reflected_without_new_signal(config, events):
    state, gw, recon = _make(config, events)
    pos = _bot_position(qty="1", avg="100")
    state.positions["BTCUSDT"] = pos
    # Bybit shows a larger position at a boosted avg price (manual add).
    gw.set_position(
        ExchangePosition(
            symbol="BTCUSDT", side=PositionSide.LONG,
            size=Decimal("1.5"), avg_price=Decimal("101"),
        )
    )
    await recon.reconcile_once()
    assert pos.qty == Decimal("1.5")
    assert pos.avg_entry_price == Decimal("101")
    assert pos.manual_added_qty == Decimal("0.5")
    # signal context preserved (impl doc §4.4 note)
    assert pos.entry_mode == EntryMode.BREAKOUT_CONFIRM
    assert pos.signal_score == Decimal("7")
    assert state.new_entries_paused()
    assert BotEventType.MANUAL_ADD_DETECTED in events.types()


async def test_manual_partial_close_reflected(config, events):
    state, gw, recon = _make(config, events)
    pos = _bot_position(qty="2", avg="100")
    state.positions["BTCUSDT"] = pos
    gw.set_position(
        ExchangePosition(
            symbol="BTCUSDT", side=PositionSide.LONG,
            size=Decimal("1.2"), avg_price=Decimal("100"),
        )
    )
    await recon.reconcile_once()
    assert pos.qty == Decimal("1.2")
    assert BotEventType.MANUAL_PARTIAL_CLOSE_DETECTED in events.types()


async def test_qty_mismatch_ignored_while_bot_order_pending(config, events):
    state, gw, recon = _make(config, events)
    pos = _bot_position(qty="2", avg="100")
    state.positions["BTCUSDT"] = pos
    state.reserve_order("exit-btc", "BTCUSDT")
    gw.set_position(
        ExchangePosition(
            symbol="BTCUSDT", side=PositionSide.LONG,
            size=Decimal("1.2"), avg_price=Decimal("100"),
        )
    )

    result = await recon.reconcile_once()

    assert result.qty_mismatches == []
    assert pos.qty == Decimal("2")
    assert not state.new_entries_paused()
    assert BotEventType.MANUAL_PARTIAL_CLOSE_DETECTED not in events.types()


async def test_qty_mismatch_ignored_during_bot_position_update(config, events):
    state, gw, recon = _make(config, events)
    pos = _bot_position(qty="2", avg="100")
    state.positions["BTCUSDT"] = pos
    state.begin_position_update("BTCUSDT")
    gw.set_position(
        ExchangePosition(
            symbol="BTCUSDT", side=PositionSide.LONG,
            size=Decimal("1.2"), avg_price=Decimal("100"),
        )
    )

    result = await recon.reconcile_once()
    state.end_position_update("BTCUSDT")

    assert result.qty_mismatches == []
    assert pos.qty == Decimal("2")
    assert not state.new_entries_paused()
    assert BotEventType.MANUAL_PARTIAL_CLOSE_DETECTED not in events.types()


async def test_external_close_marks_closed(config, events):
    state, gw, recon = _make(config, events)
    pos = _bot_position(qty="1")
    state.positions["BTCUSDT"] = pos
    # gw reports no position for BTCUSDT
    result = await recon.reconcile_once()
    assert pos.status == PositionStatus.CLOSED
    assert "BTCUSDT" in result.exchange_closes
    assert not state.new_entries_paused()
    assert BotEventType.POSITION_CLOSED in events.types()


async def test_external_position_closed_when_exchange_flat(config, events):
    state, gw, recon = _make(config, events)
    pos = Position(
        symbol="1000PEPEUSDT",
        side=PositionSide.SHORT,
        status=PositionStatus.ACTIVE,
        source=PositionSource.EXTERNAL,
        qty=Decimal("70500"),
        avg_entry_price=Decimal("0.002869"),
    )
    state.positions[pos.symbol] = pos

    result = await recon.reconcile_once()

    assert pos.status == PositionStatus.CLOSED
    assert "1000PEPEUSDT" in result.external_closes
    assert BotEventType.POSITION_CLOSED_EXTERNALLY in events.types()


async def test_external_order_detected_not_cancelled(config, events):
    state, gw, recon = _make(config, events)
    gw.open_orders.append(
        ExchangeOrder(
            symbol="BTCUSDT", order_id="ext-1", client_order_id=None,
            side=Side.BUY, order_type="Limit",
            price=Decimal("90"), qty=Decimal("1"), status=OrderStatus.NEW,
        )
    )
    result = await recon.reconcile_once()
    assert "ext-1" in result.external_orders
    assert "ext-1" in state.external_orders
    assert gw.cancelled == []  # never auto-cancel (impl doc §4.3)
    assert state.new_entries_paused()


async def test_bot_exchange_protection_order_not_flagged_external(config, events):
    state, gw, recon = _make(config, events)
    pos = Position(
        symbol="1000PEPEUSDT",
        side=PositionSide.SHORT,
        status=PositionStatus.ACTIVE,
        source=PositionSource.BOT,
        qty=Decimal("44200"),
        avg_entry_price=Decimal("0.012"),
    )
    state.positions[pos.symbol] = pos
    gw.set_position(
        ExchangePosition(
            symbol=pos.symbol,
            side=PositionSide.SHORT,
            size=pos.qty,
            avg_price=pos.avg_entry_price,
        )
    )
    gw.open_orders.append(
        ExchangeOrder(
            symbol=pos.symbol,
            order_id="bybit-sl-1",
            client_order_id=None,
            side=Side.BUY,
            order_type="Market",
            price=None,
            qty=pos.qty,
            status=OrderStatus.NEW,
            trigger_price=Decimal("0.0125"),
            stop_order_type="StopLoss",
            order_filter="tpslOrder",
        )
    )

    result = await recon.reconcile_once()

    assert result.external_orders == []
    assert state.external_orders == {}
    assert not state.new_entries_paused()


async def test_known_order_not_flagged_external(config, events):
    state, gw, recon = _make(config, events)
    from packages.core.models import Order
    from packages.core.enums import OrderType

    state.orders["c1"] = Order(
        symbol="BTCUSDT", side=Side.BUY, order_type=OrderType.LIMIT,
        qty=Decimal("1"), client_order_id="c1", order_id="known-1",
    )
    gw.open_orders.append(
        ExchangeOrder(
            symbol="BTCUSDT", order_id="known-1", client_order_id="c1",
            side=Side.BUY, order_type="Limit",
            price=Decimal("90"), qty=Decimal("1"),
        )
    )
    result = await recon.reconcile_once()
    assert result.external_orders == []


async def test_pending_bot_order_not_flagged_external_or_adopted(config, events):
    state, gw, recon = _make(config, events)
    state.reserve_order("qb-pepe", "1000PEPEUSDT")
    gw.open_orders.append(
        ExchangeOrder(
            symbol="1000PEPEUSDT", order_id="bybit-pepe", client_order_id="qb-pepe",
            side=Side.SELL, order_type="Limit",
            price=Decimal("0.002869"), qty=Decimal("70500"),
        )
    )
    gw.set_position(
        ExchangePosition(
            symbol="1000PEPEUSDT", side=PositionSide.SHORT,
            size=Decimal("70500"), avg_price=Decimal("0.002869"),
        )
    )

    result = await recon.reconcile_once()

    assert result.external_orders == []
    assert result.external_positions == []
    assert state.get_position("1000PEPEUSDT") is None
    assert not state.new_entries_paused()


async def test_position_update_not_flagged_external_or_exchange_closed(config, events):
    state, gw, recon = _make(config, events)
    state.begin_position_update("BTCUSDT")
    gw.set_position(
        ExchangePosition(
            symbol="BTCUSDT", side=PositionSide.LONG,
            size=Decimal("1"), avg_price=Decimal("100"),
        )
    )

    result = await recon.reconcile_once()

    assert result.external_positions == []
    assert state.get_position("BTCUSDT") is None

    pos = _bot_position(qty="1", avg="100")
    state.positions["BTCUSDT"] = pos
    gw.positions.pop("BTCUSDT")
    result = await recon.reconcile_once()
    state.end_position_update("BTCUSDT")

    assert result.exchange_closes == []
    assert pos.status == PositionStatus.ACTIVE


async def test_bot_prefix_order_not_flagged_external_after_restart(config, events):
    state, gw, recon = _make(config, events)
    gw.open_orders.append(
        ExchangeOrder(
            symbol="BTCUSDT", order_id="bybit-1", client_order_id="qb-restarted",
            side=Side.BUY, order_type="Limit",
            price=Decimal("90"), qty=Decimal("1"), status=OrderStatus.NEW,
        )
    )

    result = await recon.reconcile_once()

    assert result.external_orders == []
    assert state.external_orders == {}
    assert not state.new_entries_paused()


async def test_stale_bot_reduce_order_cancelled_after_position_flat(config, events):
    state, gw, recon = _make(config, events)
    gw.open_orders.append(
        ExchangeOrder(
            symbol="BTCUSDT",
            order_id="bybit-ptp",
            client_order_id="ptp-stale",
            side=Side.SELL,
            order_type="Limit",
            price=Decimal("110"),
            qty=Decimal("1"),
            status=OrderStatus.NEW,
            reduce_only=True,
        )
    )

    result = await recon.reconcile_once()

    assert result.stale_bot_orders_cancelled == ["bybit-ptp"]
    assert gw.cancelled == [("BTCUSDT", "bybit-ptp", "ptp-stale")]
    assert result.external_orders == []
    assert state.external_orders == {}
    assert not state.new_entries_paused()


async def test_persisted_open_positions_closed_when_exchange_and_runtime_flat(
    config, events
):
    logger = _PersistedPositionCleanupLogger(["ETHUSDT"])
    state, gw, recon = _make(config, events, trade_logger=logger)
    gw.set_position(
        ExchangePosition(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            size=Decimal("1"),
            avg_price=Decimal("100"),
        )
    )

    result = await recon.reconcile_once()

    assert logger.calls == [({"BTCUSDT"}, "LIVE")]
    assert result.persisted_positions_closed == ["ETHUSDT"]
    assert result.changed is True
    assert logger.summary["persisted_positions_closed"] == ["ETHUSDT"]


async def test_in_sync_no_events(config, events):
    state, gw, recon = _make(config, events)
    pos = _bot_position(qty="1", avg="100")
    state.positions["BTCUSDT"] = pos
    gw.set_position(
        ExchangePosition(
            symbol="BTCUSDT", side=PositionSide.LONG,
            size=Decimal("1"), avg_price=Decimal("100"),
            liq_price=Decimal("80"), unrealized_pnl=Decimal("5"),
        )
    )
    await recon.reconcile_once()
    assert pos.liq_price == Decimal("80")
    assert pos.unrealized_pnl == Decimal("5")
    assert not state.new_entries_paused()
    # only the RECONCILED summary event
    assert events.types() == [BotEventType.RECONCILED]
