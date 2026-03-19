"""
Execution engine: handles trade execution pipeline.

Features:
  - Market and limit order support
  - TWAP / VWAP execution algorithms
  - Slippage modeling (random + impact)
  - Order status tracking
  - Paper / Live mode routing via ExchangeAdapter
"""

from __future__ import annotations

import datetime
import logging
import math
import time
from dataclasses import dataclass
from typing import Dict, Optional

from backend.src.exchange.exchange_adapter import (ExchangeAdapter, PaperAdapter)
from backend.src.execution.circuit_breakers import ExecutionCircuitBreaker
from backend.src.execution.order_manager import OrderManager

logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    """Result of an order execution."""

    status: str
    symbol: str = ""
    side: str = ""
    price: float = 0.0
    quantity: float = 0.0
    slippage: float = 0.0
    timestamp: str = ""
    order_type: str = "market"
    order_id: str = ""
    commission: float = 0.0
    error: str = ""


class ExecutionEngine:
    """
    Handles trade execution pipeline: Strategy → Risk → Portfolio.
    Routes orders through ExchangeAdapter (paper or live).
    """

    def __init__(
        self,
        strategy_engine,
        risk_manager,
        portfolio_manager,
        adapter: Optional[ExchangeAdapter] = None,
    ):
        self.strategy_engine = strategy_engine
        self.risk_manager = risk_manager
        self.portfolio_manager = portfolio_manager

        # Exchange adapter (defaults to paper trading)
        if adapter is None:
            adapter = PaperAdapter(
                initial_cash=portfolio_manager.cash,
                commission_rate=0.001,
                max_slippage=0.001,
            )
        self.adapter = adapter

        # Order manager
        self.order_manager = OrderManager(
            adapter=adapter,
            order_timeout_seconds=60.0,
        )

        # Configuration
        self.position_size_pct = 0.02
        self.max_slippage = 0.001  # 0.1%
        self.mode = "paper" if isinstance(adapter, PaperAdapter) else "live"
        self.circuit_breaker = ExecutionCircuitBreaker()

    # --------------------------------------------------
    # Main execution pipeline
    # --------------------------------------------------

    def _build_trade_context(
        self, symbol: str, market_snapshot: Optional[Dict], trade_value: float
    ) -> Dict:
        snapshot = market_snapshot or {}
        spread_bps = float(snapshot.get("spread_bps", 0.0) or 0.0)
        imbalance = float(snapshot.get("order_book_imbalance", 0.0) or 0.0)
        bid_depth = float(snapshot.get("bid_depth", 0.0) or 0.0)
        ask_depth = float(snapshot.get("ask_depth", 0.0) or 0.0)
        total_depth = max(0.0, bid_depth + ask_depth)
        if total_depth <= 0:
            total_depth = float(snapshot.get("book_depth_usd", 0.0) or 0.0)

        return {
            "symbol": symbol,
            "spread_bps": spread_bps,
            "order_book_imbalance": imbalance,
            "book_depth_usd": total_depth,
            "stale": bool(snapshot.get("stale", False)),
            "trade_value": trade_value,
            "correlations": snapshot.get("correlations", {}) or {},
        }

    def _estimate_expected_slippage(
        self, trade_value: float, trade_context: Dict
    ) -> float:
        spread_bps = float(trade_context.get("spread_bps", 0.0) or 0.0)
        depth = float(trade_context.get("book_depth_usd", 0.0) or 0.0)

        spread_component = spread_bps / 10000.0
        if depth <= 0:
            impact_component = 0.0015
        else:
            participation = min(1.0, trade_value / max(depth, 1e-6))
            impact_component = 0.0005 * math.sqrt(participation)

        return max(0.0, spread_component + impact_component)

    def _select_order_style(
        self, signal: int, price: float, trade_context: Dict
    ) -> Dict:
        spread_bps = float(trade_context.get("spread_bps", 0.0) or 0.0)
        stale = bool(trade_context.get("stale", False))
        imbalance = float(trade_context.get("order_book_imbalance", 0.0) or 0.0)

        use_limit = spread_bps >= 8.0 or abs(imbalance) >= 0.65
        if stale:
            use_limit = True

        side_str = "buy" if signal == 1 else "sell"
        if not use_limit:
            return {"order_type": "market", "side": side_str, "limit_price": price}

        offset = max(0.0002, min(0.0015, spread_bps / 20000.0))
        if signal == 1:
            limit_price = price * (1.0 - offset)
        else:
            limit_price = price * (1.0 + offset)
        return {
            "order_type": "limit",
            "side": side_str,
            "limit_price": max(0.0, limit_price),
        }

    def _infer_primary_strategy(self, strategy_result: Optional[Dict]) -> str:
        if not strategy_result or not isinstance(strategy_result, dict):
            return ""

        raw_signals = strategy_result.get("signals")
        raw_weights = strategy_result.get("weights")
        signals = raw_signals if isinstance(raw_signals, dict) else {}
        weights = raw_weights if isinstance(raw_weights, dict) else {}
        if not signals:
            return ""

        best_name = ""
        best_score = 0.0
        for name, raw_signal in signals.items():
            try:
                contribution = abs(float(raw_signal) * float(weights.get(name, 0.0)))
            except Exception:
                contribution = 0.0
            if contribution > best_score:
                best_score = contribution
                best_name = str(name)
        return best_name

    @staticmethod
    def _strategy_for_regime(regime: Optional[Dict]) -> str:
        state = str((regime or {}).get("market_state", "")).upper()
        if state == "TREND":
            return "momentum"
        if state == "RANGE":
            return "mean_reversion"
        if state == "VOLATILE":
            return "reduced_risk"
        return "alpha_model"

    def process_market_data(
        self,
        symbol: str,
        df,
        prediction: Dict,
        price: float,
        regime: Optional[Dict] = None,
        market_snapshot: Optional[Dict] = None,
    ) -> Dict:
        """
        Full execution pipeline: signal → risk check → execute.

        Returns:
            Order result dict
        """
        started_at = time.perf_counter()
        try:
            # 0. Circuit breaker state
            if self.circuit_breaker.state.tripped:
                if not self.risk_manager.kill_switch_active:
                    self.risk_manager.activate_kill_switch(
                        f"Execution circuit breaker tripped: {self.circuit_breaker.state.trip_reason}"
                    )
                if self.mode == "live":
                    self.order_manager.cancel_all()
                return {
                    "status": "CIRCUIT_BREAKER_TRIPPED",
                    "reason": self.circuit_breaker.state.trip_reason,
                }

            # 1. Check kill switch
            if self.risk_manager.kill_switch_active:
                # Emergency: cancel all active orders
                if self.mode == "live":
                    self.order_manager.cancel_all()
                return {"status": "KILL_SWITCH_ACTIVE"}

            # 1b. Data freshness guard (strict in live mode only)
            if self.mode == "live":
                market_ts = None
                if (
                    df is not None
                    and getattr(df, "index", None) is not None
                    and len(df.index) > 0
                ):
                    try:
                        market_ts = df.index[-1].to_pydatetime()
                    except Exception:
                        market_ts = None
                fresh_ok, _ = self.circuit_breaker.evaluate_data_freshness(market_ts)
                if not fresh_ok:
                    self.risk_manager.activate_kill_switch(
                        f"Stale market data ({self.circuit_breaker.state.last_data_age_seconds:.1f}s)"
                    )
                    return {
                        "status": "DATA_STALE",
                        "data_age_seconds": round(
                            self.circuit_breaker.state.last_data_age_seconds, 2
                        ),
                    }

            # 2. Check active order timeouts
            self.order_manager.check_timeouts()

            # 3. Generate trading signal via alpha-driven pathway
            probability = float(prediction.get("probability", 0.5))
            volatility = 0.0
            if df is not None and "volatility_20" in df.columns:
                volatility = float(df["volatility_20"].iloc[-1])

            alpha_meta = prediction.get("meta_alpha") or {}
            alpha_score = float(alpha_meta.get("alpha_score", probability) or probability)
            alpha_signal = str(alpha_meta.get("signal", "HOLD")).upper()
            alpha_confidence = float(alpha_meta.get("confidence", prediction.get("confidence", 0.5)) or 0.5)

            signal = 0
            strategy_name = self._strategy_for_regime(regime)

            if alpha_score >= 0.6 and alpha_signal == "BUY":
                signal = 1
            elif alpha_score <= 0.4 and alpha_signal == "SELL":
                signal = -1

            if strategy_name == "reduced_risk":
                signal = 0

            strategy_result = {
                "signal": signal,
                "confidence": alpha_confidence,
            }

            if signal == 0:
                self.circuit_breaker.record_success()
                return {"status": "NO_SIGNAL"}

            portfolio = self.portfolio_manager.get_portfolio()

            # 4. Check for existing position
            if symbol in portfolio["positions"]:
                # Check if we should close
                pos = portfolio["positions"][symbol]
                if (pos["side"] == "long" and signal == -1) or (
                    pos["side"] == "short" and signal == 1
                ):
                    return self._close_position(symbol, price)
                return {"status": "POSITION_ALREADY_OPEN"}

            # 5. Calculate trade value using risk-based position sizing
            capital = portfolio["cash"]
            confidence = float(prediction.get("confidence", 0.5))
            
            # Capital Scaling via Rolling Sharpe
            rolling_metrics = self.portfolio_manager.get_rolling_metrics(n_trades=20)
            rolling_sharpe = rolling_metrics.get("sharpe", 1.0)
            
            position_qty = self.risk_manager.calculate_position_size(
                capital=capital,
                price=price,
                volatility=volatility,
                confidence=confidence,
                rolling_sharpe=rolling_sharpe,
                current_drawdown=portfolio.get("max_drawdown", 0.0)
            )
            trade_value = position_qty * price

            if trade_value <= 0:
                self.circuit_breaker.record_failure("no_capital")
                return {"status": "NO_CAPITAL"}

            trade_context = self._build_trade_context(
                symbol, market_snapshot, trade_value
            )

            # Entry quality filter: enforce liquidity / imbalance confirmation.
            spread_bps = float(trade_context.get("spread_bps", 0.0) or 0.0)
            imbalance = abs(float(trade_context.get("order_book_imbalance", 0.0) or 0.0))
            if spread_bps > 20.0 and imbalance < 0.05:
                self.circuit_breaker.record_success()
                return {
                    "status": "ENTRY_FILTERED",
                    "reason": "insufficient_liquidity_confirmation",
                    "alpha_score": round(alpha_score, 4),
                }

            expected_slippage = self._estimate_expected_slippage(
                trade_value, trade_context
            )

            # 6. Risk approval
            volatility = (
                float(df["volatility_20"].iloc[-1])
                if "volatility_20" in df.columns
                else 0
            )
            approval = self.risk_manager.approve_trade(
                portfolio,
                trade_value,
                volatility,
                symbol=symbol,
                trade_context=trade_context,
            )

            if not approval["approved"]:
                self.circuit_breaker.record_success()
                return {"status": "RISK_REJECTED", "reason": approval["reason"]}

            # 7. Adjust for risk recommendations
            if approval.get("adjustments", {}).get("reduce_size"):
                trade_value *= approval["adjustments"]["reduce_size"]

            # Confidence profile sizing: high=2x, medium=1x, low=0.5x.
            trade_value *= self.risk_manager.confidence_size_multiplier(alpha_confidence)

            # 8. Calculate quantity
            quantity = trade_value / price
            execution_style = self._select_order_style(signal, price, trade_context)
            side_str = execution_style["side"]
            position_side = "long" if signal == 1 else "short"

            # 9. Submit order via adapter
            if execution_style["order_type"] == "limit":
                order = self.order_manager.submit_limit_order(
                    symbol=symbol,
                    side=side_str,
                    quantity=quantity,
                    price=execution_style["limit_price"],
                )
            else:
                order = self.order_manager.submit_market_order(
                    symbol=symbol,
                    side=side_str,
                    quantity=quantity,
                    price=price,
                )

            # 10. If filled, update portfolio
            if order.status == "filled":
                self.portfolio_manager.open_position(
                    symbol=symbol,
                    quantity=order.filled_quantity,
                    price=order.filled_price,
                    side=position_side,
                    strategy_name=strategy_name,
                    metadata={
                        "regime": (
                            (regime or {}).get("trend", "default")
                            if isinstance(regime, dict)
                            else "default"
                        ),
                    },
                )

                slippage = abs(order.filled_price - price) / price if price > 0 else 0
                latency_ms = (time.perf_counter() - started_at) * 1000.0
                exec_ok, exec_reason = self.circuit_breaker.evaluate_execution_quality(
                    latency_ms=latency_ms,
                    slippage_pct=slippage,
                )
                if not exec_ok:
                    self.risk_manager.activate_kill_switch(
                        f"Execution quality breach ({exec_reason})"
                    )
                self.circuit_breaker.record_success()

                result = OrderResult(
                    status="TRADE_EXECUTED",
                    symbol=symbol,
                    side=position_side.upper(),
                    price=order.filled_price,
                    quantity=order.filled_quantity,
                    slippage=slippage,
                    timestamp=order.created_at
                    or datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    order_type=order.order_type,
                    order_id=order.order_id,
                    commission=order.commission,
                )

                logger.info(
                    "[%s] Executed %s %s @ %.2f qty=%.6f slip=%.4f%% comm=%.4f",
                    self.mode.upper(),
                    position_side,
                    symbol,
                    order.filled_price,
                    order.filled_quantity,
                    slippage * 100,  # Convert slip back to % formatting if it was slip=...%
                    order.commission,
                )

                return {
                    "status": result.status,
                    "symbol": result.symbol,
                    "side": result.side,
                    "price": round(result.price, 4),
                    "quantity": round(result.quantity, 8),
                    "slippage": round(result.slippage, 6),
                    "timestamp": result.timestamp,
                    "order_id": result.order_id,
                    "commission": round(result.commission, 6),
                    "mode": self.mode,
                    "latency_ms": round(latency_ms, 3),
                    "order_type": result.order_type,
                    "expected_slippage": round(expected_slippage, 6),
                    "alpha_score": round(alpha_score, 6),
                    "alpha_confidence": round(alpha_confidence, 6),
                    "strategy_name": strategy_name,
                }

            elif order.status == "rejected":
                tripped = self.circuit_breaker.record_failure("order_rejected")
                if tripped:
                    self.risk_manager.activate_kill_switch(
                        "Consecutive order rejections"
                    )
                return {
                    "status": "ORDER_REJECTED",
                    "error": order.error,
                    "mode": self.mode,
                }

            else:
                # Order still pending (shouldn't happen for market orders)
                tripped = self.circuit_breaker.record_failure("order_pending")
                if tripped:
                    self.risk_manager.activate_kill_switch("Consecutive pending orders")
                return {
                    "status": "ORDER_PENDING",
                    "order_id": order.order_id,
                    "mode": self.mode,
                }

        except Exception as e:
            logger.error("Execution error: %s", e)
            tripped = self.circuit_breaker.record_failure("execution_exception")
            if tripped:
                self.risk_manager.activate_kill_switch(
                    "Consecutive execution exceptions"
                )
            return {"status": "EXECUTION_ERROR", "error": str(e)}

    # --------------------------------------------------
    # Close position
    # --------------------------------------------------

    def _close_position(self, symbol: str, price: float) -> Dict:
        """Close an existing position via exchange adapter."""
        portfolio = self.portfolio_manager.get_portfolio()
        pos = portfolio["positions"].get(symbol)

        if not pos:
            return {"status": "NO_POSITION"}

        quantity = pos["quantity"]
        side_str = "sell" if pos["side"] == "long" else "buy"

        # Submit close order
        order = self.order_manager.submit_market_order(
            symbol=symbol,
            side=side_str,
            quantity=quantity,
            price=price,
        )

        if order.status == "filled":
            closed_trade = self.portfolio_manager.close_position(
                symbol, order.filled_price
            )

            if closed_trade and hasattr(
                self.strategy_engine, "record_strategy_outcome"
            ):
                strategy_name = str(closed_trade.get("strategy_name", "") or "")
                if strategy_name:
                    try:
                        pnl_fraction = 0.0
                        entry = float(closed_trade.get("entry_price", 0.0) or 0.0)
                        exit_price = float(closed_trade.get("exit_price", 0.0) or 0.0)
                        side = str(closed_trade.get("side", "long"))
                        if entry > 0:
                            if side == "short":
                                pnl_fraction = (entry - exit_price) / entry
                            else:
                                pnl_fraction = (exit_price - entry) / entry
                        self.strategy_engine.record_strategy_outcome(
                            strategy_name, pnl_fraction
                        )
                    except Exception:
                        pass

            return {
                "status": "POSITION_CLOSED",
                "symbol": symbol,
                "price": round(order.filled_price, 4),
                "timestamp": order.created_at
                or datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "order_id": order.order_id,
                "commission": round(order.commission, 6),
                "mode": self.mode,
            }

        return {
            "status": "CLOSE_FAILED",
            "error": order.error or f"Order status: {order.status}",
            "mode": self.mode,
        }

    # --------------------------------------------------
    # TWAP Execution
    # --------------------------------------------------

    def compute_twap_schedule(self, total_quantity: float, num_slices: int = 5) -> list:
        """
        Compute TWAP (Time-Weighted Average Price) execution schedule.

        Returns list of quantities to execute at each interval.
        """
        slice_qty = total_quantity / num_slices
        return [round(slice_qty, 8)] * num_slices

    # --------------------------------------------------
    # VWAP Execution
    # --------------------------------------------------

    def compute_vwap_schedule(
        self, total_quantity: float, volume_profile: list
    ) -> list:
        """
        Compute VWAP execution schedule based on volume profile.

        Args:
            total_quantity: total quantity to execute
            volume_profile: list of relative volume at each interval

        Returns list of quantities proportional to volume.
        """
        if not volume_profile:
            # Default to TWAP if no volume profile
            return [total_quantity]

        total_vol = sum(volume_profile)
        if total_vol <= 0:
            return [total_quantity / len(volume_profile)] * len(volume_profile)

        # Ensure precision limits on tiny slices
        slices = [round(total_quantity * (v / total_vol), 8) for v in volume_profile]

        # Adjust remainder due to rounding
        rem = total_quantity - sum(slices)
        if len(slices) > 0 and abs(rem) > 1e-8:
            slices[-1] = round(slices[-1] + rem, 8)

        return slices

    # --------------------------------------------------
    # Stop / TP management
    # --------------------------------------------------

    def check_exit_conditions(
        self,
        symbol: str,
        current_price: float,
        highest_price: float,
        atr: float = 0.0,
        bars_held: int = 0,
        max_holding_bars: int = 288,
    ) -> Optional[str]:
        """
        Check if any exit condition is triggered.

        Returns: "stop_loss", "trailing_stop", "take_profit", "time_exit", or None
        """
        portfolio = self.portfolio_manager.get_portfolio()

        if symbol not in portfolio["positions"]:
            return None

        pos = portfolio["positions"][symbol]
        entry_price = pos["entry_price"]
        side = pos["side"]

        # Time-based exit (stale position)
        if bars_held > 0 and bars_held >= max_holding_bars:
            return "time_exit"

        # Optional stored values from entry
        metadata = pos.get("metadata") or {}
        entry_atr = float(metadata.get("atr", atr) or atr)
        confidence = float(metadata.get("confidence", 0.5) or 0.5)

        # Stop loss (computes dynamic distance based on entry ATR)
        stop = self.risk_manager.calculate_stop_loss(entry_price, side, atr=entry_atr)
        if side == "long" and current_price <= stop:
            return "stop_loss"
        if side == "short" and current_price >= stop:
            return "stop_loss"

        risk_distance = abs(entry_price - stop)
        current_r = (
            ((current_price - entry_price) / max(risk_distance, 1e-8))
            if side == "long"
            else ((entry_price - current_price) / max(risk_distance, 1e-8))
        )

        # Trailing stop only activates after >= 2R move in favor.
        if current_r >= 2.0:
            trail = self.risk_manager.calculate_trailing_stop(
                entry_price, highest_price, side
            )
            if side == "long" and current_price <= trail:
                return "trailing_stop"
            if side == "short" and current_price >= trail:
                return "trailing_stop"

        # Take profit uses dynamic 3R..5R target from confidence profile.
        dynamic_rr = self.risk_manager.dynamic_rr_target(confidence)
        tp = self.risk_manager.calculate_take_profit(
            entry_price,
            side,
            stop_loss_price=stop,
            rr_ratio=dynamic_rr,
        )
        if side == "long" and current_price >= tp:
            return "take_profit"
        if side == "short" and current_price <= tp:
            return "take_profit"

        return None

    # --------------------------------------------------
    # Order state queries
    # --------------------------------------------------

    def get_active_orders(self) -> list:
        """Get currently active (non-terminal) orders."""
        return self.order_manager.get_active_orders()

    def get_order_history(self, limit: int = 50) -> list:
        """Get recent order history."""
        return self.order_manager.get_recent_history(limit)

    def get_order_statistics(self) -> dict:
        """Get order execution statistics."""
        return self.order_manager.get_statistics()

    def get_circuit_breaker_status(self) -> Dict:
        """Get execution circuit breaker status for APIs and monitoring."""
        return self.circuit_breaker.get_status()

    def reset_circuit_breaker(self) -> Dict:
        """Reset breaker state after operator intervention."""
        self.circuit_breaker.reset()
        return self.circuit_breaker.get_status()
