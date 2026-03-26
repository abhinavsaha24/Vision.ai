from __future__ import annotations

import math
import random
from dataclasses import dataclass

from backend.src.platform.live.types import ExecutionReport, RiskDecision, SignalDecision


@dataclass(slots=True)
class _Position:
    side: str
    quantity: float
    entry_price: float


class RiskEngine:
    def __init__(
        self,
        max_position_notional: float,
        max_symbol_notional: float,
        max_concurrent_trades: int,
        max_daily_trades: int,
        cooldown_after_loss_s: float,
        target_volatility_bps: float,
    ):
        self.max_position_notional = max_position_notional
        self.max_symbol_notional = max_symbol_notional
        self.max_concurrent_trades = max_concurrent_trades
        self.max_daily_trades = max_daily_trades
        self.cooldown_after_loss_s = cooldown_after_loss_s
        self.target_volatility_bps = target_volatility_bps
        self.cooldown_until_ms: int = 0
        self.open_trades: int = 0
        self.daily_trade_count: int = 0
        self._day_bucket: int | None = None
        self._symbol_open_notional: dict[str, float] = {}

    def _rollover_day_if_needed(self, now_ms: int) -> None:
        day_bucket = int(now_ms // 86_400_000)
        if self._day_bucket is None:
            self._day_bucket = day_bucket
            return
        if day_bucket != self._day_bucket:
            self._day_bucket = day_bucket
            self.daily_trade_count = 0

    def evaluate(
        self,
        now_ms: int,
        signal: SignalDecision,
        price: float,
        realized_vol_bps: float,
        current_position: _Position | None,
    ) -> RiskDecision:
        self._rollover_day_if_needed(now_ms)
        if now_ms < self.cooldown_until_ms:
            return RiskDecision(False, "cooldown_active")

        if self.daily_trade_count >= self.max_daily_trades:
            return RiskDecision(False, "daily_trade_limit")

        if current_position is None and self.open_trades >= self.max_concurrent_trades:
            return RiskDecision(False, "max_concurrent_trades")

        vol_scalar = 1.0
        if realized_vol_bps > 0:
            vol_scalar = min(1.0, self.target_volatility_bps / max(realized_vol_bps, 1e-6))

        confidence_scalar = max(0.25, min(1.0, signal.score))
        notional = self.max_position_notional * vol_scalar * confidence_scalar

        if notional <= 10.0:
            return RiskDecision(False, "size_too_small")

        is_open_or_scale = current_position is None or current_position.side == signal.side
        if is_open_or_scale:
            current_symbol_notional = float(self._symbol_open_notional.get(signal.symbol, 0.0))
            if current_symbol_notional + notional > self.max_symbol_notional:
                return RiskDecision(False, "symbol_notional_limit")

        quantity = notional / max(price, 1e-9)
        return RiskDecision(True, "approved", quantity=quantity, notional=notional)

    def on_new_position(self, symbol: str = "", notional: float = 0.0) -> None:
        self.daily_trade_count += 1
        self.open_trades += 1
        if symbol and notional > 0.0:
            self._symbol_open_notional[symbol] = float(self._symbol_open_notional.get(symbol, 0.0)) + float(notional)

    def on_position_closed(self, pnl: float, now_ms: int, symbol: str = "", closed_notional: float = 0.0) -> None:
        self.open_trades = max(0, self.open_trades - 1)
        if symbol and closed_notional > 0.0:
            prev = float(self._symbol_open_notional.get(symbol, 0.0))
            self._symbol_open_notional[symbol] = max(0.0, prev - float(closed_notional))
        if pnl < 0:
            self.cooldown_until_ms = int(now_ms + (self.cooldown_after_loss_s * 1000.0))


class ExecutionEngine:
    """Latency-aware market order simulator with slippage and fill probability."""

    def __init__(
        self,
        rng: random.Random | None = None,
        min_latency_ms: float = 8.0,
        max_latency_ms: float = 55.0,
        partial_fill_threshold: float = 0.18,
        partial_fill_min_ratio: float = 0.35,
    ):
        self._positions: dict[str, _Position] = {}
        self._rng = rng or random.Random()
        self.min_latency_ms = max(0.0, float(min_latency_ms))
        self.max_latency_ms = max(self.min_latency_ms, float(max_latency_ms))
        self.partial_fill_threshold = max(0.0, float(partial_fill_threshold))
        self.partial_fill_min_ratio = min(1.0, max(0.05, float(partial_fill_min_ratio)))

    def get_position(self, symbol: str) -> _Position | None:
        if symbol:
            return self._positions.get(symbol)
        if len(self._positions) == 1:
            return next(iter(self._positions.values()))
        return None

    @property
    def position(self) -> _Position | None:
        return self.get_position("")

    def execute(
        self,
        now_ms: int,
        signal: SignalDecision,
        quantity: float,
        price: float,
        spread_bps: float,
        visible_liquidity: float,
    ) -> ExecutionReport:
        simulated_latency_ms = self._rng.uniform(self.min_latency_ms, self.max_latency_ms)
        exec_ts_ms = int(now_ms + simulated_latency_ms)
        if not math.isfinite(quantity) or not math.isfinite(price) or quantity <= 0.0 or price <= 0.0:
            return ExecutionReport(
                symbol=signal.symbol,
                ts_ms=exec_ts_ms,
                status="rejected",
                side=signal.side,
                quantity=max(0.0, float(quantity if math.isfinite(quantity) else 0.0)),
                requested_price=float(price if math.isfinite(price) else 0.0),
                fill_price=0.0,
                slippage_bps=0.0,
                fill_probability=0.0,
                detail="invalid_order_input",
                requested_quantity=max(0.0, float(quantity if math.isfinite(quantity) else 0.0)),
                filled_quantity=0.0,
                simulated_latency_ms=simulated_latency_ms,
            )

        if signal.side not in {"long", "short"}:
            raise ValueError(f"invalid_signal_side:{signal.side}")

        spread_bps = max(0.0, float(spread_bps if math.isfinite(spread_bps) else 0.0))
        visible_liquidity = max(0.0, float(visible_liquidity if math.isfinite(visible_liquidity) else 0.0))

        participation = 0.0
        if visible_liquidity > 0:
            participation = min(1.0, quantity / max(visible_liquidity, 1e-9))

        slippage_bps = self._estimate_slippage_bps(spread_bps, participation)
        fill_probability = self._fill_probability(spread_bps, participation, visible_liquidity)

        fill_ratio = 1.0
        if participation >= self.partial_fill_threshold:
            fill_ratio = self._rng.uniform(self.partial_fill_min_ratio, 1.0)
        executed_quantity = max(0.0, quantity * fill_ratio)

        if self._rng.random() > fill_probability:
            return ExecutionReport(
                symbol=signal.symbol,
                ts_ms=exec_ts_ms,
                status="rejected",
                side=signal.side,
                quantity=quantity,
                requested_price=price,
                fill_price=0.0,
                slippage_bps=slippage_bps,
                fill_probability=fill_probability,
                detail="fill_probability_rejection",
                requested_quantity=quantity,
                filled_quantity=0.0,
                simulated_latency_ms=simulated_latency_ms,
            )

        sign = 1.0 if signal.side == "long" else -1.0
        fill_price = price * (1.0 + sign * slippage_bps / 10000.0)

        realized_pnl = 0.0
        detail = ""
        symbol = signal.symbol
        position = self._positions.get(symbol)
        if position is None:
            self._positions[symbol] = _Position(signal.side, executed_quantity, fill_price)
            status = "opened"
        elif position.side == signal.side:
            total_qty = position.quantity + executed_quantity
            avg_price = ((position.entry_price * position.quantity) + (fill_price * executed_quantity)) / max(total_qty, 1e-9)
            self._positions[symbol] = _Position(signal.side, total_qty, avg_price)
            status = "scaled"
        else:
            closing_qty = min(position.quantity, executed_quantity)
            direction = 1.0 if position.side == "long" else -1.0
            realized_pnl = (fill_price - position.entry_price) * closing_qty * direction
            remaining_qty = position.quantity - closing_qty
            if remaining_qty <= 1e-9:
                self._positions.pop(symbol, None)
                status = "closed"
            else:
                self._positions[symbol] = _Position(position.side, remaining_qty, position.entry_price)
                status = "partial_close"

        if executed_quantity < quantity:
            detail = "partial_fill"

        return ExecutionReport(
            symbol=signal.symbol,
            ts_ms=exec_ts_ms,
            status=status,
            side=signal.side,
            quantity=executed_quantity,
            requested_price=price,
            fill_price=fill_price,
            slippage_bps=slippage_bps,
            fill_probability=fill_probability,
            pnl=realized_pnl,
            detail=detail,
            requested_quantity=quantity,
            filled_quantity=executed_quantity,
            simulated_latency_ms=simulated_latency_ms,
        )

    @staticmethod
    def _estimate_slippage_bps(spread_bps: float, participation: float) -> float:
        impact = 0.6 * math.sqrt(max(0.0, participation))
        return max(0.05, (spread_bps * 0.30) + impact)

    @staticmethod
    def _fill_probability(spread_bps: float, participation: float, visible_liquidity: float) -> float:
        spread_penalty = min(0.55, max(0.0, spread_bps / 50.0))
        part_penalty = min(0.65, participation * 0.9)
        liquidity_bonus = min(0.20, max(0.0, visible_liquidity / 50.0))
        p = 0.96 - spread_penalty - part_penalty + liquidity_bonus
        return max(0.05, min(0.995, p))
