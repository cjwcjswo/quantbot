"""RiskManager: the final approver before any order (arch doc §6.19, impl §13).

Applies Stop Distance Guard (§13.2), account limits (positions, per-symbol and
total open risk, daily loss), the leverage policy (§13.3) and the Liquidation
Guard (§13.4), then returns a sized, leveraged decision with SL/TP levels. If it
rejects, the order is never placed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from packages.config.settings import AppConfig
from packages.core.enums import PositionSide, SignalDirection
from packages.core.errors import RiskRejection
from packages.core.models import Position, SymbolMeta
from packages.entry.entry_timing_engine import EntryDecision
from packages.risk.leverage import choose_leverage, max_leverage
from packages.risk.levels import estimate_liq_price, stop_loss_price, take_profit_price
from packages.risk.position_sizing import compute_size
from packages.universe import meets_min_notional, meets_min_qty

_STOP_DISTANCE_ATR_MIN = Decimal("0.5")  # impl doc §13.2
_STOP_DISTANCE_ATR_MAX = Decimal("1.5")


@dataclass
class RiskContext:
    equity: Decimal
    open_positions: list[Position] = field(default_factory=list)
    daily_loss_percent: Decimal = Decimal(0)  # positive => losing
    intraday_drawdown_percent: Decimal = Decimal(0)
    consecutive_losses: int = 0


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str = ""
    side: PositionSide | None = None
    qty: Decimal = Decimal(0)
    leverage: Decimal = Decimal(0)
    notional: Decimal = Decimal(0)
    stop_loss_price: Decimal | None = None
    take_profit_price: Decimal | None = None
    liq_price: Decimal | None = None
    risk_usdt: Decimal = Decimal(0)


def _reject(reason: str) -> RiskDecision:
    return RiskDecision(approved=False, reason=reason)


def _position_risk(p: Position) -> Decimal:
    if p.initial_risk_per_unit is not None:
        return p.initial_risk_per_unit * p.qty
    return Decimal(0)


class RiskManager:
    def __init__(self, config: AppConfig) -> None:
        self.cfg = config

    def approve(
        self,
        decision: EntryDecision,
        *,
        entry_price: Decimal,
        atr: Decimal,
        symbol_meta: SymbolMeta,
        ctx: RiskContext,
    ) -> RiskDecision:
        risk = self.cfg.risk
        side = (
            PositionSide.LONG
            if decision.direction == SignalDirection.LONG
            else PositionSide.SHORT
        )

        if atr <= 0 or entry_price <= 0:
            return _reject("INVALID_MARKET_DATA")

        stop = stop_loss_price(entry_price, atr, decision.stop_atr, side)

        # Stop Distance Guard (§13.2)
        stop_distance_atr = abs(entry_price - stop) / atr
        if stop_distance_atr < _STOP_DISTANCE_ATR_MIN:
            return _reject("STOP_TOO_TIGHT")
        if stop_distance_atr > _STOP_DISTANCE_ATR_MAX:
            return _reject("STOP_TOO_WIDE")

        # Account-level blocks
        if ctx.daily_loss_percent >= Decimal(str(risk.daily_max_loss_percent)):
            return _reject("DAILY_LOSS_LIMIT")
        if ctx.intraday_drawdown_percent >= Decimal(str(risk.intraday_drawdown_percent)):
            return _reject("INTRADAY_DRAWDOWN")
        if len(ctx.open_positions) >= self.cfg.bot.max_active_positions:
            return _reject("MAX_POSITIONS")
        if any(p.symbol == decision.symbol for p in ctx.open_positions):
            return _reject("SYMBOL_ALREADY_OPEN")
        same_dir = sum(1 for p in ctx.open_positions if p.side == side)
        if same_dir >= risk.max_same_direction_positions:
            return _reject("MAX_SAME_DIRECTION")

        # Leverage cap (§13.3)
        lev_cap = max_leverage(
            entry_mode=decision.entry_mode,
            atr_percent=self._atr_percent(atr, entry_price),
            consecutive_losses=ctx.consecutive_losses,
            daily_loss_percent=ctx.daily_loss_percent,
            config=risk,
        )
        max_notional = ctx.equity * lev_cap

        # Sizing (§13.1)
        try:
            sizing = compute_size(
                equity=ctx.equity,
                account_risk_per_trade_percent=Decimal(
                    str(risk.account_risk_per_trade_percent)
                ),
                position_fraction=decision.position_fraction,
                entry_price=entry_price,
                stop_loss_price=stop,
                qty_step=symbol_meta.qty_step,
                max_notional=max_notional,
            )
        except RiskRejection as exc:
            return _reject(exc.reason)

        if not meets_min_qty(sizing.qty, symbol_meta):
            return _reject("BELOW_MIN_QTY")
        if not meets_min_notional(sizing.qty, entry_price, symbol_meta):
            return _reject("BELOW_MIN_NOTIONAL")

        # Risk exposure limits
        symbol_risk_pct = sizing.risk_usdt / ctx.equity * Decimal(100)
        if symbol_risk_pct > Decimal(str(risk.max_symbol_risk_percent)):
            return _reject("SYMBOL_RISK_EXCEEDED")
        total_risk = sum((_position_risk(p) for p in ctx.open_positions), Decimal(0))
        total_risk_pct = (total_risk + sizing.risk_usdt) / ctx.equity * Decimal(100)
        if total_risk_pct > Decimal(str(risk.max_total_open_risk_percent)):
            return _reject("TOTAL_RISK_EXCEEDED")

        # Leverage to set, and Liquidation Guard (§13.4)
        leverage = choose_leverage(
            notional=sizing.notional,
            equity=ctx.equity,
            max_lev=lev_cap,
            min_lev=Decimal(risk.min_leverage),
        )
        liq = estimate_liq_price(entry_price, leverage, side)
        guard = self.cfg.liquidation_guard
        liq_distance = abs(liq - entry_price)
        if liq_distance / entry_price * Decimal(100) < Decimal(
            str(guard.min_liquidation_distance_percent)
        ):
            return _reject("LIQ_TOO_CLOSE_PCT")
        if liq_distance / atr < Decimal(str(guard.min_liquidation_distance_atr)):
            return _reject("LIQ_TOO_CLOSE_ATR")
        if guard.block_if_liq_price_inside_stop and self._liq_inside_stop(
            side, liq, stop
        ):
            return _reject("LIQ_INSIDE_STOP")

        take_profit = take_profit_price(
            entry_price, stop, side, Decimal(str(self.cfg.tpsl.initial_take_profit_r))
        )

        return RiskDecision(
            approved=True,
            side=side,
            qty=sizing.qty,
            leverage=leverage,
            notional=sizing.notional,
            stop_loss_price=stop,
            take_profit_price=take_profit,
            liq_price=liq,
            risk_usdt=sizing.risk_usdt,
        )

    @staticmethod
    def _atr_percent(atr: Decimal, price: Decimal) -> Decimal:
        return atr / price * Decimal(100) if price > 0 else Decimal(0)

    @staticmethod
    def _liq_inside_stop(side: PositionSide, liq: Decimal, stop: Decimal) -> bool:
        # liq is "inside" (reached before) the stop if it is on the entry side of it.
        if side == PositionSide.LONG:
            return liq >= stop
        return liq <= stop
