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
from typing import Dict, List, Optional
from collections import deque
from datetime import datetime, timezone

from src.Binance.exchange_adapter import ExchangeAdapter, Order

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

    def __init__(self, adapter: ExchangeAdapter,
                 order_timeout_seconds: float = 60.0,
                 max_history: int = 1000):
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

    def submit_market_order(self, symbol: str, side: str,
                            quantity: float, price: float = 0.0) -> Order:
        """Submit a market order and track its lifecycle."""

        order = self.adapter.place_market_order(symbol, side, quantity, price)
        self.total_submitted += 1

        if order.status == "filled":
            self.total_filled += 1
            self.order_history.append(order)
            logger.info(
                f"ORDER FILLED: {order.order_id} {side} {quantity:.6f} {symbol} "
                f"@ {order.filled_price:.2f}"
            )
        elif order.status == "rejected":
            self.total_rejected += 1
            self.order_history.append(order)
            logger.warning(f"ORDER REJECTED: {order.order_id} — {order.error}")
        else:
            # Still pending/submitted — track as active
            self.active_orders[order.order_id] = order
            logger.info(f"ORDER SUBMITTED: {order.order_id} → {order.status}")

        return order

    def submit_limit_order(self, symbol: str, side: str,
                           quantity: float, price: float) -> Order:
        """Submit a limit order and track its lifecycle."""

        order = self.adapter.place_limit_order(symbol, side, quantity, price)
        self.total_submitted += 1

        if order.status == "filled":
            self.total_filled += 1
            self.order_history.append(order)
        elif order.status == "rejected":
            self.total_rejected += 1
            self.order_history.append(order)
            logger.warning(f"LIMIT ORDER REJECTED: {order.order_id} — {order.error}")
        else:
            self.active_orders[order.order_id] = order
            logger.info(
                f"LIMIT ORDER SUBMITTED: {order.order_id} "
                f"{side} {quantity:.6f} {symbol} @ {price:.2f}"
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
                        f"ORDER FILLED: {order_id} "
                        f"@ {updated.filled_price:.2f}"
                    )
                elif updated.status == "cancelled":
                    self.total_cancelled += 1
                    logger.info(f"ORDER CANCELLED: {order_id}")

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
                logger.warning(
                    f"ORDER TIMEOUT: {order_id} age={age:.0f}s > {self.order_timeout}s"
                )
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
        logger.critical(f"CANCEL ALL: {total} orders cancelled (symbol={symbol or 'ALL'})")
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

    def get_statistics(self) -> Dict:
        """Order manager statistics."""
        return {
            "total_submitted": self.total_submitted,
            "total_filled": self.total_filled,
            "total_rejected": self.total_rejected,
            "total_cancelled": self.total_cancelled,
            "active_orders": len(self.active_orders),
            "fill_rate": (
                round(self.total_filled / self.total_submitted, 4)
                if self.total_submitted > 0 else 0
            ),
        }
