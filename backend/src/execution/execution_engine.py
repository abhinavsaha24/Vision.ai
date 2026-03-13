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

import logging
import datetime
from dataclasses import dataclass
from typing import Dict, Optional

from backend.src.exchange.exchange_adapter import ExchangeAdapter, PaperAdapter, Order
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

    def __init__(self, strategy_engine, risk_manager, portfolio_manager,
                 adapter: Optional[ExchangeAdapter] = None):
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

    # --------------------------------------------------
    # Main execution pipeline
    # --------------------------------------------------

    def process_market_data(self, symbol: str, df, prediction: Dict,
                            price: float, regime: Optional[Dict] = None) -> Dict:
        """
        Full execution pipeline: signal → risk check → execute.

        Returns:
            Order result dict
        """
        try:
            # 1. Check kill switch
            if self.risk_manager.kill_switch_active:
                # Emergency: cancel all active orders
                if self.mode == "live":
                    self.order_manager.cancel_all()
                return {"status": "KILL_SWITCH_ACTIVE"}

            # 2. Check active order timeouts
            self.order_manager.check_timeouts()

            # 3. Generate trading signal
            signal = self.strategy_engine.generate_signal(df, prediction, regime)

            if signal == 0:
                return {"status": "NO_SIGNAL"}

            portfolio = self.portfolio_manager.get_portfolio()

            # 4. Check for existing position
            if symbol in portfolio["positions"]:
                # Check if we should close
                pos = portfolio["positions"][symbol]
                if (pos["side"] == "long" and signal == -1) or \
                   (pos["side"] == "short" and signal == 1):
                    return self._close_position(symbol, price)
                return {"status": "POSITION_ALREADY_OPEN"}

            # 5. Calculate trade value
            capital = portfolio["cash"]
            trade_value = capital * self.position_size_pct

            if trade_value <= 0:
                return {"status": "NO_CAPITAL"}

            # 6. Risk approval
            volatility = float(df["volatility_20"].iloc[-1]) if "volatility_20" in df.columns else 0
            approval = self.risk_manager.approve_trade(portfolio, trade_value, volatility)

            if not approval["approved"]:
                return {"status": "RISK_REJECTED", "reason": approval["reason"]}

            # 7. Adjust for risk recommendations
            if approval.get("adjustments", {}).get("reduce_size"):
                trade_value *= approval["adjustments"]["reduce_size"]

            # 8. Calculate quantity
            quantity = trade_value / price
            side_str = "buy" if signal == 1 else "sell"
            position_side = "long" if signal == 1 else "short"

            # 9. Submit order via adapter
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
                )

                slippage = abs(order.filled_price - price) / price if price > 0 else 0

                result = OrderResult(
                    status="TRADE_EXECUTED",
                    symbol=symbol,
                    side=position_side.upper(),
                    price=order.filled_price,
                    quantity=order.filled_quantity,
                    slippage=slippage,
                    timestamp=order.created_at or datetime.datetime.utcnow().isoformat(),
                    order_type=order.order_type,
                    order_id=order.order_id,
                    commission=order.commission,
                )

                logger.info(
                    f"[{self.mode.upper()}] Executed {position_side} {symbol} "
                    f"@ {order.filled_price:.2f} qty={order.filled_quantity:.6f} "
                    f"slip={slippage:.4%} comm={order.commission:.4f}"
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
                }

            elif order.status == "rejected":
                return {
                    "status": "ORDER_REJECTED",
                    "error": order.error,
                    "mode": self.mode,
                }

            else:
                # Order still pending (shouldn't happen for market orders)
                return {
                    "status": "ORDER_PENDING",
                    "order_id": order.order_id,
                    "mode": self.mode,
                }

        except Exception as e:
            logger.error(f"Execution error: {e}")
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
            self.portfolio_manager.close_position(symbol, order.filled_price)

            return {
                "status": "POSITION_CLOSED",
                "symbol": symbol,
                "price": round(order.filled_price, 4),
                "timestamp": order.created_at or datetime.datetime.utcnow().isoformat(),
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

    def compute_twap_schedule(self, total_quantity: float,
                              num_slices: int = 5) -> list:
        """
        Compute TWAP (Time-Weighted Average Price) execution schedule.

        Returns list of quantities to execute at each interval.
        """
        slice_qty = total_quantity / num_slices
        return [round(slice_qty, 8)] * num_slices

    # --------------------------------------------------
    # VWAP Execution
    # --------------------------------------------------

    def compute_vwap_schedule(self, total_quantity: float,
                              volume_profile: list) -> list:
        """
        Compute VWAP execution schedule based on volume profile.

        Args:
            total_quantity: total quantity to execute
            volume_profile: list of relative volume at each interval

        Returns list of quantities proportional to volume.
        """
        if not volume_profile:
            return [total_quantity]

        total_vol = sum(volume_profile)
        if total_vol <= 0:
            return [total_quantity / len(volume_profile)] * len(volume_profile)

        return [
            round(total_quantity * (v / total_vol), 8)
            for v in volume_profile
        ]

    # --------------------------------------------------
    # Stop / TP management
    # --------------------------------------------------

    def check_exit_conditions(self, symbol: str, current_price: float,
                              highest_price: float) -> Optional[str]:
        """
        Check if any exit condition is triggered.

        Returns: "stop_loss", "trailing_stop", "take_profit", or None
        """
        portfolio = self.portfolio_manager.get_portfolio()

        if symbol not in portfolio["positions"]:
            return None

        pos = portfolio["positions"][symbol]
        entry_price = pos["entry_price"]
        side = pos["side"]

        # Stop loss
        stop = self.risk_manager.calculate_stop_loss(entry_price, side)
        if side == "long" and current_price <= stop:
            return "stop_loss"
        if side == "short" and current_price >= stop:
            return "stop_loss"

        # Trailing stop
        trail = self.risk_manager.calculate_trailing_stop(entry_price, highest_price, side)
        if side == "long" and current_price <= trail:
            return "trailing_stop"
        if side == "short" and current_price >= trail:
            return "trailing_stop"

        # Take profit
        tp = self.risk_manager.calculate_take_profit(entry_price, side)
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