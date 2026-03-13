"""
Execution engine: handles trade execution pipeline.

Features:
  - Market and limit order support
  - TWAP / VWAP execution algorithms
  - Slippage modeling (random + impact)
  - Order status tracking
"""

from __future__ import annotations

import logging
import datetime
from dataclasses import dataclass
from typing import Dict, Optional

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
    error: str = ""


class ExecutionEngine:
    """
    Handles trade execution pipeline: Strategy → Risk → Portfolio.
    Supports market/limit orders and execution algorithms.
    """

    def __init__(self, strategy_engine, risk_manager, portfolio_manager):
        self.strategy_engine = strategy_engine
        self.risk_manager = risk_manager
        self.portfolio_manager = portfolio_manager

        # Configuration
        self.position_size_pct = 0.02
        self.max_slippage = 0.001  # 0.1%
        self.mode = "paper"  # "paper" or "live"

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
                return {"status": "KILL_SWITCH_ACTIVE"}

            # 2. Generate trading signal
            signal = self.strategy_engine.generate_signal(df, prediction, regime)

            if signal == 0:
                return {"status": "NO_SIGNAL"}

            portfolio = self.portfolio_manager.get_portfolio()

            # 3. Check for existing position
            if symbol in portfolio["positions"]:
                # Check if we should close
                pos = portfolio["positions"][symbol]
                if (pos["side"] == "long" and signal == -1) or \
                   (pos["side"] == "short" and signal == 1):
                    return self._close_position(symbol, price)
                return {"status": "POSITION_ALREADY_OPEN"}

            # 4. Calculate trade value
            capital = portfolio["cash"]
            trade_value = capital * self.position_size_pct

            if trade_value <= 0:
                return {"status": "NO_CAPITAL"}

            # 5. Risk approval
            volatility = float(df["volatility_20"].iloc[-1]) if "volatility_20" in df.columns else 0
            approval = self.risk_manager.approve_trade(portfolio, trade_value, volatility)

            if not approval["approved"]:
                return {"status": "RISK_REJECTED", "reason": approval["reason"]}

            # 6. Adjust for risk recommendations
            if approval.get("adjustments", {}).get("reduce_size"):
                trade_value *= approval["adjustments"]["reduce_size"]

            # 7. Apply slippage
            slippage = self._compute_slippage(price, trade_value)
            execution_price = price * (1 + slippage) if signal == 1 else price * (1 - slippage)

            quantity = trade_value / execution_price

            # 8. Execute
            side = "long" if signal == 1 else "short"

            self.portfolio_manager.open_position(
                symbol=symbol,
                quantity=quantity,
                price=execution_price,
                side=side,
            )

            order = OrderResult(
                status="TRADE_EXECUTED",
                symbol=symbol,
                side=side.upper(),
                price=execution_price,
                quantity=quantity,
                slippage=slippage,
                timestamp=datetime.datetime.utcnow().isoformat(),
                order_type="market",
            )

            logger.info(f"Executed {side} {symbol} @ {execution_price:.2f} qty={quantity:.6f}")

            return {
                "status": order.status,
                "symbol": order.symbol,
                "side": order.side,
                "price": round(order.price, 4),
                "quantity": round(order.quantity, 8),
                "slippage": round(order.slippage, 6),
                "timestamp": order.timestamp,
            }

        except Exception as e:
            logger.error(f"Execution error: {e}")
            return {"status": "EXECUTION_ERROR", "error": str(e)}

    # --------------------------------------------------
    # Close position
    # --------------------------------------------------

    def _close_position(self, symbol: str, price: float) -> Dict:
        """Close an existing position."""
        slippage = self._compute_slippage(price, 0)
        close_price = price * (1 - slippage)  # conservative

        self.portfolio_manager.close_position(symbol, close_price)

        return {
            "status": "POSITION_CLOSED",
            "symbol": symbol,
            "price": round(close_price, 4),
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }

    # --------------------------------------------------
    # Slippage modeling
    # --------------------------------------------------

    def _compute_slippage(self, price: float, trade_value: float) -> float:
        """
        Compute realistic slippage.
        Combines random component + market impact.
        """
        import numpy as np

        # Random slippage (0 to max_slippage)
        random_slip = np.random.uniform(0, self.max_slippage * 0.5)

        # Market impact: larger trades have more impact
        if trade_value > 0 and price > 0:
            # Simplified square-root impact model
            notional_ratio = trade_value / (price * 1000)  # relative to avg daily volume
            impact = min(self.max_slippage * 0.5, notional_ratio * 0.01)
        else:
            impact = 0

        return random_slip + impact

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