"""RiskManager: the final approver before any order (arch doc §6.19, impl §13).

Applies Stop Distance Guard (§13.2), account limits (positions, per-symbol and
total open risk, daily loss), the leverage policy (§13.3) and the Liquidation
Guard (§13.4), then returns a sized, leveraged decision with SL/TP levels. If it
rejects, the order is never placed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from packages.config.settings import AppConfig
from packages.core.enums import EntryMode, PositionSide, SignalDirection
from packages.core.errors import RiskRejection
from packages.core.models import Position, SymbolMeta
from packages.entry.entry_timing_engine import EntryDecision
from packages.risk.leverage import choose_leverage, max_leverage
from packages.risk.levels import estimate_liq_price, stop_loss_price, take_profit_price
from packages.risk.position_sizing import compute_size
from packages.universe import meets_min_notional, meets_min_qty, round_price_to_tick


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
    stop_metadata: dict[str, object] | None = None


def _reject(
    reason: str,
    stop_metadata: dict[str, object] | None = None,
) -> RiskDecision:
    return RiskDecision(approved=False, reason=reason, stop_metadata=stop_metadata)


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

        stop_metadata = dict(decision.stop_metadata or {})

        if atr <= 0 or entry_price <= 0:
            return _reject("INVALID_MARKET_DATA", stop_metadata)

        atr_stop = self._round_stop_to_tick(
            stop_loss_price(entry_price, atr, decision.stop_atr, side),
            side,
            symbol_meta.tick_size,
        )
        structure_stop = self._structure_stop_price(decision, side, symbol_meta)
        selected_stop = self._select_stop(side, atr_stop, structure_stop)
        min_distance_stop = self._min_distance_stop_price(
            decision.entry_mode, entry_price, side, symbol_meta
        )
        stop = self._select_stop(side, selected_stop, min_distance_stop)
        stop_metadata = self._with_stop_metadata(
            decision=decision,
            side=side,
            entry_price=entry_price,
            atr=atr,
            atr_stop=atr_stop,
            structure_stop=structure_stop,
            min_distance_stop=min_distance_stop,
            stop_before_min_distance=selected_stop,
            selected_stop=stop,
            metadata=stop_metadata,
        )

        # Stop Distance Guard (§13.2)
        stop_distance_atr = abs(entry_price - stop) / atr
        max_stop_distance_atr = self._max_stop_distance_atr(decision.entry_mode)
        if stop_distance_atr < Decimal(str(risk.min_stop_distance_atr)):
            stop_metadata["risk_reject_reason"] = "STOP_DISTANCE_TOO_NARROW"
            return _reject("STOP_DISTANCE_TOO_NARROW", stop_metadata)
        if stop_distance_atr > max_stop_distance_atr:
            stop_metadata["risk_reject_reason"] = "STOP_DISTANCE_TOO_WIDE"
            return _reject("STOP_DISTANCE_TOO_WIDE", stop_metadata)

        # Account-level blocks
        if ctx.daily_loss_percent >= Decimal(str(risk.daily_max_loss_percent)):
            return _reject("DAILY_LOSS_LIMIT", stop_metadata)
        if ctx.intraday_drawdown_percent >= Decimal(str(risk.intraday_drawdown_percent)):
            return _reject("INTRADAY_DRAWDOWN", stop_metadata)
        if len(ctx.open_positions) >= self.cfg.bot.max_active_positions:
            return _reject("MAX_POSITIONS", stop_metadata)
        if any(p.symbol == decision.symbol for p in ctx.open_positions):
            return _reject("SYMBOL_ALREADY_OPEN", stop_metadata)
        same_dir = sum(1 for p in ctx.open_positions if p.side == side)
        if same_dir >= risk.max_same_direction_positions:
            return _reject("MAX_SAME_DIRECTION", stop_metadata)

        # Leverage cap (§13.3)
        high_quality = self._is_high_quality(decision)
        stop_metadata["high_quality"] = high_quality
        stop_distance_percent = abs(entry_price - stop) / entry_price * Decimal(100)
        lev_cap = max_leverage(
            entry_mode=decision.entry_mode,
            atr_percent=self._atr_percent(atr, entry_price),
            consecutive_losses=ctx.consecutive_losses,
            daily_loss_percent=ctx.daily_loss_percent,
            config=risk,
            high_quality=high_quality,
        )
        thin_stop_cap = self._thin_stop_leverage_cap(stop_distance_percent)
        if thin_stop_cap is not None:
            lev_cap = min(lev_cap, thin_stop_cap)
            stop_metadata["thin_stop_leverage_cap_applied"] = True
            stop_metadata["thin_stop_distance_percent"] = str(
                risk.thin_stop_distance_percent
            )
            stop_metadata["thin_stop_max_leverage"] = str(risk.thin_stop_max_leverage)
        else:
            stop_metadata["thin_stop_leverage_cap_applied"] = False
        max_notional = ctx.equity * lev_cap
        target_notional_percent = self._target_notional_percent(
            decision,
            high_quality=high_quality,
        )
        target_notional = (
            ctx.equity * target_notional_percent / Decimal(100)
            if target_notional_percent is not None
            else None
        )
        risk_based_notional = self._risk_based_notional(
            equity=ctx.equity,
            risk_percent=Decimal(str(risk.account_risk_per_trade_percent)),
            position_fraction=decision.position_fraction,
            entry_price=entry_price,
            stop_loss_price=stop,
        )

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
                target_notional=target_notional,
            )
        except RiskRejection as exc:
            return _reject(exc.reason, stop_metadata)
        if target_notional is not None:
            stop_metadata["target_notional_percent"] = str(target_notional_percent)
            stop_metadata["target_notional"] = str(target_notional)
            stop_metadata["risk_based_notional"] = str(risk_based_notional)
            stop_metadata["target_notional_applied"] = (
                target_notional > risk_based_notional
            )

        if not meets_min_qty(sizing.qty, symbol_meta):
            return _reject("BELOW_MIN_QTY", stop_metadata)
        if not meets_min_notional(sizing.qty, entry_price, symbol_meta):
            return _reject("BELOW_MIN_NOTIONAL", stop_metadata)

        # Risk exposure limits
        symbol_risk_pct = sizing.risk_usdt / ctx.equity * Decimal(100)
        if symbol_risk_pct > Decimal(str(risk.max_symbol_risk_percent)):
            return _reject("SYMBOL_RISK_EXCEEDED", stop_metadata)
        total_risk = sum((_position_risk(p) for p in ctx.open_positions), Decimal(0))
        total_risk_pct = (total_risk + sizing.risk_usdt) / ctx.equity * Decimal(100)
        if total_risk_pct > Decimal(str(risk.max_total_open_risk_percent)):
            return _reject("TOTAL_RISK_EXCEEDED", stop_metadata)

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
            return _reject("LIQ_TOO_CLOSE_PCT", stop_metadata)
        if liq_distance / atr < Decimal(str(guard.min_liquidation_distance_atr)):
            return _reject("LIQ_TOO_CLOSE_ATR", stop_metadata)
        if guard.block_if_liq_price_inside_stop and self._liq_inside_stop(
            side, liq, stop
        ):
            return _reject("LIQ_INSIDE_STOP", stop_metadata)

        take_profit = round_price_to_tick(
            take_profit_price(
                entry_price,
                stop,
                side,
                Decimal(str(self.cfg.tpsl.initial_take_profit_r)),
            ),
            symbol_meta.tick_size,
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
            stop_metadata=stop_metadata,
        )

    def _structure_stop_price(
        self,
        decision: EntryDecision,
        side: PositionSide,
        symbol_meta: SymbolMeta,
    ) -> Decimal | None:
        if decision.structure_stop_price is None:
            return None
        if not self._structure_stop_enabled(decision.entry_mode):
            return None
        return self._round_stop_to_tick(
            decision.structure_stop_price,
            side,
            symbol_meta.tick_size,
        )

    def _structure_stop_enabled(self, entry_mode: EntryMode) -> bool:
        c = self.cfg.structure_stop
        if not c.enabled:
            return False
        if entry_mode == EntryMode.PRE_BREAKOUT_SCOUT and not c.use_structure_stop_for_scout:
            return False
        if entry_mode == EntryMode.RETEST_CONFIRM and not c.use_structure_stop_for_retest:
            return False
        return entry_mode.value in set(c.apply_to_entry_modes)

    def _min_distance_stop_price(
        self,
        entry_mode: EntryMode,
        entry_price: Decimal,
        side: PositionSide,
        symbol_meta: SymbolMeta,
    ) -> Decimal | None:
        min_percent = self._min_stop_distance_percent(entry_mode)
        if min_percent <= 0:
            return None
        offset = entry_price * min_percent / Decimal(100)
        raw = (
            entry_price - offset
            if side == PositionSide.LONG
            else entry_price + offset
        )
        return self._round_stop_to_tick(raw, side, symbol_meta.tick_size)

    def _min_stop_distance_percent(self, entry_mode: EntryMode) -> Decimal:
        global_min = Decimal(str(self.cfg.risk.min_stop_distance_percent))
        if entry_mode == EntryMode.PRE_BREAKOUT_SCOUT:
            scout_min = Decimal(
                str(self.cfg.entry.pre_breakout.min_stop_distance_percent)
            )
            return max(global_min, scout_min)
        if entry_mode in (EntryMode.BREAKOUT_CONFIRM, EntryMode.RETEST_CONFIRM):
            return global_min
        return Decimal(0)

    @staticmethod
    def _round_stop_to_tick(
        price: Decimal, side: PositionSide, tick: Decimal
    ) -> Decimal:
        """Round SL away from entry direction so tick rounding never narrows risk."""
        if tick <= 0:
            return price
        rounding = ROUND_FLOOR if side == PositionSide.LONG else ROUND_CEILING
        ticks = (price / tick).to_integral_value(rounding=rounding)
        return ticks * tick

    @staticmethod
    def _select_stop(
        side: PositionSide, atr_stop: Decimal, structure_stop: Decimal | None
    ) -> Decimal:
        if structure_stop is None:
            return atr_stop
        if side == PositionSide.LONG:
            return min(atr_stop, structure_stop)
        return max(atr_stop, structure_stop)

    def _max_stop_distance_atr(self, entry_mode: EntryMode) -> Decimal:
        if entry_mode == EntryMode.PRE_BREAKOUT_SCOUT:
            return Decimal(str(self.cfg.risk.scout_max_stop_distance_atr))
        if entry_mode == EntryMode.RETEST_CONFIRM:
            limit = Decimal(str(self.cfg.risk.retest_max_stop_distance_atr))
            if self._structure_stop_enabled(entry_mode):
                limit = min(
                    limit,
                    Decimal(str(self.cfg.structure_stop.max_stop_distance_atr)),
                )
            return limit
        return Decimal(str(self.cfg.risk.max_stop_distance_atr))

    def _target_notional_percent(
        self,
        decision: EntryDecision,
        *,
        high_quality: bool,
    ) -> Decimal | None:
        config = self.cfg.risk.target_notional_percent
        if not config.enabled:
            return None

        if decision.entry_mode == EntryMode.PRE_BREAKOUT_SCOUT:
            value = (
                config.scout_compression
                if decision.has_compression is True
                else config.scout_no_compression
            )
        elif decision.entry_mode == EntryMode.BREAKOUT_CONFIRM:
            value = config.breakout_confirm
        elif decision.entry_mode == EntryMode.RETEST_CONFIRM:
            value = config.retest_confirm
        else:
            return None

        percent = Decimal(str(value))
        if high_quality:
            percent = max(percent, Decimal(str(config.high_quality)))
        return percent if percent > 0 else None

    def _is_high_quality(self, decision: EntryDecision) -> bool:
        config = self.cfg.risk.target_notional_percent
        if not config.enabled:
            return False
        return decision.score >= Decimal(str(config.high_quality_min_score))

    def _thin_stop_leverage_cap(self, stop_distance_percent: Decimal) -> Decimal | None:
        threshold = Decimal(str(self.cfg.risk.thin_stop_distance_percent))
        cap = Decimal(str(self.cfg.risk.thin_stop_max_leverage))
        if threshold <= 0 or cap <= 0:
            return None
        return cap if stop_distance_percent <= threshold else None

    @staticmethod
    def _risk_based_notional(
        *,
        equity: Decimal,
        risk_percent: Decimal,
        position_fraction: Decimal,
        entry_price: Decimal,
        stop_loss_price: Decimal,
    ) -> Decimal:
        stop_distance_percent = abs(entry_price - stop_loss_price) / entry_price
        if stop_distance_percent <= 0:
            return Decimal(0)
        mode_risk = equity * risk_percent / Decimal(100) * position_fraction
        return mode_risk / stop_distance_percent

    def _with_stop_metadata(
        self,
        *,
        decision: EntryDecision,
        side: PositionSide,
        entry_price: Decimal,
        atr: Decimal,
        atr_stop: Decimal,
        structure_stop: Decimal | None,
        min_distance_stop: Decimal | None,
        stop_before_min_distance: Decimal,
        selected_stop: Decimal,
        metadata: dict[str, object],
    ) -> dict[str, object]:
        stop_distance_atr = abs(entry_price - selected_stop) / atr
        stop_distance_percent = (
            abs(entry_price - selected_stop) / entry_price * Decimal(100)
        )
        out = dict(metadata)
        out.update(
            {
                "entry_mode": decision.entry_mode.value,
                "symbol": decision.symbol,
                "side": side.value,
                "atr_percent_1m": str(self._atr_percent(atr, entry_price)),
                "resolved_stop_atr": str(decision.stop_atr),
                "atr_stop_price": str(atr_stop),
                "structure_stop_enabled": self._structure_stop_enabled(
                    decision.entry_mode
                ),
                "structure_stop_price": str(structure_stop)
                if structure_stop is not None
                else None,
                "min_stop_distance_percent": str(
                    self._min_stop_distance_percent(decision.entry_mode)
                ),
                "min_distance_stop_price": str(min_distance_stop)
                if min_distance_stop is not None
                else None,
                "min_distance_stop_applied": (
                    selected_stop != stop_before_min_distance
                    if min_distance_stop is not None
                    else None
                ),
                "selected_stop_price": str(selected_stop),
                "stop_distance_atr": str(stop_distance_atr),
                "stop_distance_percent": str(stop_distance_percent),
            }
        )
        return {k: v for k, v in out.items() if v is not None}

    @staticmethod
    def _atr_percent(atr: Decimal, price: Decimal) -> Decimal:
        return atr / price * Decimal(100) if price > 0 else Decimal(0)

    @staticmethod
    def _liq_inside_stop(side: PositionSide, liq: Decimal, stop: Decimal) -> bool:
        # liq is "inside" (reached before) the stop if it is on the entry side of it.
        if side == PositionSide.LONG:
            return liq >= stop
        return liq <= stop
