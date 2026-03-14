"""
System monitoring and metrics collection.

Tracks:
  - Request count and latency percentiles
  - API error rates
  - Strategy performance snapshots
  - Risk alert history
"""

from __future__ import annotations

import time
import logging
from collections import defaultdict, deque
from typing import Dict, List
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class RequestMetric:
    path: str
    status_code: int
    latency_ms: float
    timestamp: float


class MonitoringService:
    """
    Lightweight in-memory metrics collector.
    Keeps a rolling window of metrics for the dashboard.
    """

    def __init__(self, max_history: int = 10000):
        self.max_history = max_history
        self._requests: deque = deque(maxlen=max_history)
        self._errors: deque = deque(maxlen=1000)
        self._strategy_snapshots: deque = deque(maxlen=500)
        self._risk_alerts: deque = deque(maxlen=500)
        self._start_time = time.time()

    # --------------------------------------------------
    # Record events
    # --------------------------------------------------

    def record_request(self, path: str, status_code: int, latency_ms: float):
        self._requests.append(RequestMetric(
            path=path, status_code=status_code,
            latency_ms=latency_ms, timestamp=time.time(),
        ))

    def record_error(self, path: str, error: str):
        self._errors.append({
            "path": path, "error": error,
            "timestamp": time.time(),
        })

    def record_strategy_snapshot(self, strategy_data: dict):
        self._strategy_snapshots.append({
            **strategy_data,
            "timestamp": time.time(),
        })

    def record_risk_alert(self, alert: dict):
        self._risk_alerts.append({
            **alert,
            "timestamp": time.time(),
        })

    # --------------------------------------------------
    # Get metrics
    # --------------------------------------------------

    def get_metrics(self) -> Dict:
        """Get comprehensive system metrics."""
        now = time.time()
        uptime = now - self._start_time

        # Request stats (last 5 minutes)
        window = 300
        recent = [r for r in self._requests if now - r.timestamp < window]

        latencies = [r.latency_ms for r in recent] if recent else [0]
        error_count = sum(1 for r in recent if r.status_code >= 400)

        # Path breakdown
        path_counts: Dict[str, int] = defaultdict(int)
        for r in recent:
            prefix = "/" + r.path.strip("/").split("/")[0]
            path_counts[prefix] += 1

        return {
            "uptime_seconds": round(uptime, 0),
            "requests": {
                "total_5min": len(recent),
                "errors_5min": error_count,
                "error_rate": round(error_count / max(len(recent), 1), 4),
                "requests_per_second": round(len(recent) / window, 2),
            },
            "latency_ms": {
                "p50": round(float(np.percentile(latencies, 50)), 1),
                "p95": round(float(np.percentile(latencies, 95)), 1),
                "p99": round(float(np.percentile(latencies, 99)), 1),
                "avg": round(float(np.mean(latencies)), 1),
            },
            "path_breakdown": dict(path_counts),
            "recent_errors": list(self._errors)[-10:],
            "strategy_snapshots": list(self._strategy_snapshots)[-5:],
            "risk_alerts": list(self._risk_alerts)[-10:],
        }
