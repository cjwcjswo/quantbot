"""Tests for reconciliation cadence triggers + dedicated logging (impl doc §4.2)."""

from sqlalchemy import func, select

from apps.bot.runtime.runtime_state import RuntimeState
from packages.messaging import EventBus
from packages.reconciliation import ManualInterventionHandler, ReconciliationManager
from packages.storage import (
    ManualInterventionLogRow,
    ReconciliationLogRow,
    TradeLogger,
)
from tests.fakes import FakeGateway
from tests.fakes.builders import symbol_meta  # noqa: F401  (keeps builders importable)


def _recon(config, events, logger=None):
    state = RuntimeState()
    bus = EventBus(redis=None, sink=events)
    handler = ManualInterventionHandler(
        state, bus, config.manual_intervention, trade_logger=logger
    )
    return ReconciliationManager(
        FakeGateway(), state, handler, bus, config.reconciliation, trade_logger=logger
    ), state


def test_mark_order_event_shortens_interval(config, events):
    recon, _ = _recon(config, events)
    assert recon.next_interval_sec() == config.reconciliation.interval_sec_when_flat
    recon.mark_order_event()
    assert recon.next_interval_sec() == config.reconciliation.interval_sec_after_order_event
    # one-shot: reverts afterwards
    assert recon.next_interval_sec() == config.reconciliation.interval_sec_when_flat


async def _count(sf, model):
    async with sf() as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar_one()


async def test_reconciliation_logged(config, events, session_factory):
    tl = TradeLogger(session_factory)
    recon, _ = _recon(config, events, logger=tl)
    await recon.reconcile_once()
    assert await _count(session_factory, ReconciliationLogRow) == 1


async def test_manual_intervention_logged(config, events, session_factory):
    from decimal import Decimal

    from packages.core.enums import PositionSide
    from packages.core.models import ExchangePosition

    tl = TradeLogger(session_factory)
    recon, state = _recon(config, events, logger=tl)
    recon._gw.set_position(  # external position on the exchange
        ExchangePosition(symbol="ETHUSDT", side=PositionSide.SHORT,
                         size=Decimal("2"), avg_price=Decimal("2000"))
    )
    await recon.reconcile_once()
    assert await _count(session_factory, ManualInterventionLogRow) == 1
