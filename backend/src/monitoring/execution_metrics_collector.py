"""
Execution metrics collector: aggregates execution quality metrics during trading.

Collects:
  - Latency metrics (order submission to fill time)
  - Slippage metrics (expected vs actual fill price)
  - Fill rates and order statistics
  - Execution quality assessment

Used by trading loop to feed real metrics to readiness system.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from typing import Dict

logger = logging.getLogger(__name__)


class ExecutionMetricsCollector:
    """
    Collects execution statistics from order manager and order results.

    Maintains a rolling window of metrics and computes aggregates.
    Fed by trading loop after each cycle to track execution quality.
    """

    def __init__(self, window_size: int = 100):
        """
        Initialize metrics collector.

        Args:
            window_size: Number of recent trades to include in rolling average
        """
        self.window_size = window_size
        self.metrics_history: deque = deque(maxlen=window_size)
        self.last_update = None
        self.total_orders = 0

    def record_order_result(self, order_result: Dict):
        """
        Record execution of a single order.

        Args:
            order_result: Dict with keys:
                - latency_ms: float, time from submission to fill
                - slippage_bps: float, slippage in basis points
                - status: str, "FILLED", "REJECTED", "CANCELLED", etc
                - symbol: str
                - side: str
                - quantity: float
                - price: float
                - filled_price: float
        """
        self.metrics_history.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "latency_ms": float(order_result.get("latency_ms", 0.0)),
                "slippage_bps": float(order_result.get("slippage_bps", 0.0)),
                "status": order_result.get("status", "UNKNOWN"),
                "symbol": order_result.get("symbol", ""),
            }
        )
        self.last_update = datetime.now(timezone.utc)
        self.total_orders += 1

    def update_from_order_manager(self, order_manager) -> bool:
        """
        Update metrics from an OrderManager instance.

        Extracts execution metrics directly from order manager's statistics.

        Args:
            order_manager: ExecutionEngine's OrderManager instance

        Returns:
            True if metrics were updated, False otherwise
        """
        try:
            stats = order_manager.get_statistics()

            self.metrics_history.append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "avg_latency_ms": float(stats.get("avg_latency_ms", 0.0)),
                    "avg_slippage_bps": float(stats.get("avg_slippage_bps", 0.0)),
                    "median_latency_ms": float(stats.get("median_latency_ms", 0.0)),
                    "median_slippage_bps": float(stats.get("median_slippage_bps", 0.0)),
                    "p95_latency_ms": float(stats.get("p95_latency_ms", 0.0)),
                    "p95_slippage_bps": float(stats.get("p95_slippage_bps", 0.0)),
                    "orders_analyzed": int(stats.get("orders_analyzed", 0)),
                    "fill_rate": float(stats.get("fill_rate", 0.0)),
                    "total_filled": int(stats.get("total_filled", 0)),
                }
            )
            self.last_update = datetime.now(timezone.utc)

            return True
        except Exception as e:
            logger.warning("Failed to update metrics from order manager: %s", e)
            return False

    def get_current_metrics(self) -> Dict:
        """
        Get current aggregated execution metrics.

        Returns:
            Dict with current latency, slippage, and quality assessment
        """
        if not self.metrics_history:
            return {
                "avg_latency_ms": 0.0,
                "avg_slippage_bps": 0.0,
                "quality": "unknown",
                "status": "no_data",
            }

        # Get the most recent snapshot
        latest = self.metrics_history[-1]

        avg_latency = float(latest.get("avg_latency_ms", 0.0))
        avg_slippage = float(latest.get("avg_slippage_bps", 0.0))

        return {
            "avg_latency_ms": round(avg_latency, 2),
            "avg_slippage_bps": round(avg_slippage, 2),
            "quality": self._assess_quality(avg_latency, avg_slippage),
            "status": "active" if self.last_update else "idle",
            "last_update": self.last_update.isoformat() if self.last_update else None,
        }

    def _assess_quality(self, latency_ms: float, slippage_bps: float) -> str:
        """
        Assess execution quality based on latency and slippage.

        Quality tiers:
          - "excellent": latency < 100ms, slippage < 5bps
          - "good": latency < 500ms, slippage < 10bps
          - "degraded": latency < 1500ms, slippage < 30bps
          - "critical": latency >= 1500ms OR slippage >= 30bps
          - "unknown": no data
        """
        if latency_ms < 100 and slippage_bps < 5:
            return "excellent"
        elif latency_ms < 500 and slippage_bps < 10:
            return "good"
        elif latency_ms < 1500 and slippage_bps < 30:
            return "degraded"
        else:
            return "critical"

    def get_full_report(self) -> Dict:
        """
        Get comprehensive execution metrics report.

        Returns:
            Dict with current and historical metrics
        """
        current = self.get_current_metrics()

        # Calculate rolling statistics
        latencies = [m.get("avg_latency_ms", 0.0) for m in self.metrics_history]
        slippages = [m.get("avg_slippage_bps", 0.0) for m in self.metrics_history]

        if latencies and slippages:
            avg_lat = sum(latencies) / len(latencies)
            avg_slip = sum(slippages) / len(slippages)
            max_lat = max(latencies)
            max_slip = max(slippages)
        else:
            avg_lat = avg_slip = max_lat = max_slip = 0.0

        return {
            "current": current,
            "rolling": {
                "avg_latency_ms": round(avg_lat, 2),
                "avg_slippage_bps": round(avg_slip, 2),
                "max_latency_ms": round(max_lat, 2),
                "max_slippage_bps": round(max_slip, 2),
                "window_size": len(self.metrics_history),
            },
            "total_orders_tracked": self.total_orders,
        }
