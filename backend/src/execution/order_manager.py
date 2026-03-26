"""
Order manager: tracks order lifecycle and maintains order history.

Responsibilities:
  - Order state machine (pending → submitted → filled | cancelled | rejected)
  - Active order tracking with timeout management
  - Order history log for audit and analysis
  - Emergency cancel-all capability
"""

from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List

from backend.src.exchange.exchange_adapter import ExchangeAdapter, Order

logger = logging.getLogger(__name__)


class OrderManager:
    """
    Manages the full lifecycle of orders.

    Sits between the ExecutionEngine and ExchangeAdapter:
      ExecutionEngine → OrderManager → ExchangeAdapter

    Tracks:
      - All submitted orders (active + historical)
      - Order state transitions
      - Fill confirmations
      - Timeout and stale order cleanup
    """

    def __init__(
        self,
        adapter: ExchangeAdapter,
        order_timeout_seconds: float = 60.0,
        max_history: int = 1000,
    ):
        self.adapter = adapter
        self.order_timeout = order_timeout_seconds
        self.max_history = max_history

        # Active orders (non-terminal)
        self.active_orders: Dict[str, Order] = {}

        # Completed order history
        self.order_history: deque = deque(maxlen=max_history)

        # Statistics
        self.total_submitted = 0
        self.total_filled = 0
        self.total_rejected = 0
        self.total_cancelled = 0

    # --------------------------------------------------
    # Order submission
    # --------------------------------------------------

    def submit_market_order(
        self, symbol: str, side: str, quantity: float, price: float = 0.0
    ) -> Order:
        """Submit a market order and track its lifecycle."""

        order = self.adapter.place_market_order(symbol, side, quantity, price)
        self.total_submitted += 1

        if order.status == "filled":
            self.total_filled += 1
            self.order_history.append(order)
            logger.info(
                "ORDER FILLED: %s %s %.6f %s @ %.2f",
                order.order_id,
                side,
                quantity,
                symbol,
                order.filled_price,
            )
        elif order.status == "rejected":
            self.total_rejected += 1
            self.order_history.append(order)
            logger.warning("ORDER REJECTED: {order.order_id} — %s", order.error)
        else:
            # Still pending/submitted — track as active
            self.active_orders[order.order_id] = order
            logger.info("ORDER SUBMITTED: {order.order_id} → %s", order.status)

        return order

    def submit_limit_order(
        self, symbol: str, side: str, quantity: float, price: float
    ) -> Order:
        """Submit a limit order and track its lifecycle."""

        order = self.adapter.place_limit_order(symbol, side, quantity, price)
        self.total_submitted += 1

        if order.status == "filled":
            self.total_filled += 1
            self.order_history.append(order)
        elif order.status == "rejected":
            self.total_rejected += 1
            self.order_history.append(order)
            logger.warning("LIMIT ORDER REJECTED: {order.order_id} — %s", order.error)
        else:
            self.active_orders[order.order_id] = order
            logger.info(
                "LIMIT ORDER SUBMITTED: %s %s %.6f %s @ %.2f",
                order.order_id,
                side,
                quantity,
                symbol,
                price,
            )

        return order

    # --------------------------------------------------
    # Order monitoring
    # --------------------------------------------------

    def check_active_orders(self) -> List[Order]:
        """
        Poll status of all active orders.
        Moves terminal orders to history.

        Returns list of newly filled/cancelled orders.
        """
        resolved = []
        to_remove = []

        for order_id, order in self.active_orders.items():
            updated = self.adapter.get_order_status(order_id, order.symbol)

            if updated.is_terminal():
                to_remove.append(order_id)
                self.order_history.append(updated)
                resolved.append(updated)

                if updated.status == "filled":
                    self.total_filled += 1
                    logger.info(
                        "ORDER FILLED: %s @ %.2f", order_id, updated.filled_price
                    )
                elif updated.status == "cancelled":
                    self.total_cancelled += 1
                    logger.info("ORDER CANCELLED: %s", order_id)

        for oid in to_remove:
            del self.active_orders[oid]

        return resolved

    def check_timeouts(self) -> List[Order]:
        """Cancel orders that have exceeded the timeout threshold."""
        now = time.time()
        timed_out = []

        for order_id, order in list(self.active_orders.items()):
            # Parse creation time
            try:
                created = datetime.fromisoformat(
                    order.created_at.replace("Z", "+00:00")
                )
                age = now - created.timestamp()
            except (ValueError, AttributeError):
                age = 0

            if age > self.order_timeout:
                logger.warning("ORDER TIMEOUT: %s age=%.0fs > %ss", order_id, age, self.order_timeout)
                result = self.adapter.cancel_order(order_id, order.symbol)
                timed_out.append(result)
                self.total_cancelled += 1
                self.order_history.append(result)
                del self.active_orders[order_id]

        return timed_out

    # --------------------------------------------------
    # Emergency operations
    # --------------------------------------------------

    def cancel_all(self, symbol: str = "") -> int:
        """Cancel all active orders (emergency kill switch support)."""

        # Cancel on exchange
        exchange_cancelled = self.adapter.cancel_all_orders(symbol)

        # Cancel locally tracked
        local_cancelled = 0
        to_remove = []
        for order_id, order in self.active_orders.items():
            if not symbol or order.symbol == symbol:
                order.status = "cancelled"
                order.updated_at = datetime.now(timezone.utc).isoformat()
                self.order_history.append(order)
                to_remove.append(order_id)
                local_cancelled += 1

        for oid in to_remove:
            del self.active_orders[oid]

        total = max(exchange_cancelled, local_cancelled)
        self.total_cancelled += total
        logger.critical("CANCEL ALL: {total} orders cancelled (symbol=%s)", symbol or 'ALL')
        return total

    # --------------------------------------------------
    # State queries
    # --------------------------------------------------

    def get_active_orders(self) -> List[Dict]:
        """Return active orders as serializable dicts."""
        return [
            {
                "order_id": o.order_id,
                "symbol": o.symbol,
                "side": o.side,
                "type": o.order_type,
                "quantity": o.quantity,
                "price": o.price,
                "status": o.status,
                "filled_qty": o.filled_quantity,
                "created_at": o.created_at,
            }
            for o in self.active_orders.values()
        ]

    def get_recent_history(self, limit: int = 50) -> List[Dict]:
        """Return recent order history as serializable dicts."""
        recent = list(self.order_history)[-limit:]
        return [
            {
                "order_id": o.order_id,
                "symbol": o.symbol,
                "side": o.side,
                "type": o.order_type,
                "quantity": round(o.quantity, 8),
                "price": round(o.price, 4),
                "filled_price": round(o.filled_price, 4),
                "status": o.status,
                "commission": round(o.commission, 6),
                "created_at": o.created_at,
            }
            for o in recent
        ]

    def get_execution_metrics(self) -> Dict:
        """
        Calculate execution quality metrics from filled orders.

        Returns:
            Dict with avg_latency_ms, avg_slippage_bps, and related stats
        """
        filled_orders = [o for o in self.order_history if o.status == "filled"]

        if not filled_orders:
            return {
                "avg_latency_ms": 0.0,
                "avg_slippage_bps": 0.0,
                "median_latency_ms": 0.0,
                "median_slippage_bps": 0.0,
                "orders_analyzed": 0,
            }

        latencies = []
        slippages = []

        for order in filled_orders:
            # Calculate latency (time from creation to fill)
            try:
                created_time = datetime.fromisoformat(
                    order.created_at.replace("Z", "+00:00")
                )
                filled_time = (
                    datetime.fromisoformat(order.updated_at.replace("Z", "+00:00"))
                    if hasattr(order, "updated_at") and order.updated_at
                    else created_time
                )

                latency_sec = (filled_time - created_time).total_seconds()
                latency_ms = max(0.0, latency_sec * 1000.0)
                latencies.append(latency_ms)
            except (ValueError, AttributeError, TypeError):
                latencies.append(0.0)

            # Calculate slippage (expected vs actual fill price)
            try:
                expected_price = float(order.price)
                filled_price = float(order.filled_price)

                if expected_price > 0:
                    # Slippage in basis points (1 bps = 0.01%)
                    slippage_pct = abs(filled_price - expected_price) / expected_price
                    slippage_bps = slippage_pct * 10000.0
                    slippages.append(slippage_bps)
                else:
                    slippages.append(0.0)
            except (ValueError, TypeError):
                slippages.append(0.0)

        import statistics

        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        avg_slippage = sum(slippages) / len(slippages) if slippages else 0.0
        median_latency = statistics.median(latencies) if latencies else 0.0
        median_slippage = statistics.median(slippages) if slippages else 0.0

        return {
            "avg_latency_ms": round(avg_latency, 2),
            "avg_slippage_bps": round(avg_slippage, 2),
            "median_latency_ms": round(median_latency, 2),
            "median_slippage_bps": round(median_slippage, 2),
            "orders_analyzed": len(filled_orders),
            "p95_latency_ms": round(
                sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0, 2
            ),
            "p95_slippage_bps": round(
                sorted(slippages)[int(len(slippages) * 0.95)] if slippages else 0, 2
            ),
        }

    def get_statistics(self) -> Dict:
        """Order manager statistics including execution quality metrics."""
        exec_metrics = self.get_execution_metrics()
        return {
            "total_submitted": self.total_submitted,
            "total_filled": self.total_filled,
            "total_rejected": self.total_rejected,
            "total_cancelled": self.total_cancelled,
            "active_orders": len(self.active_orders),
            "fill_rate": (
                round(self.total_filled / self.total_submitted, 4)
                if self.total_submitted > 0
                else 0
            ),
            **exec_metrics,
        }
