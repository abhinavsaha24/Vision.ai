"""
System monitoring and metrics collection.

Tracks:
  - Request count and latency percentiles
  - API error rates
  - Market data / ML / trade execution latency
  - Strategy performance snapshots
  - Risk alert history
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict

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

        # Pipeline latency tracking
        self._pipeline_latencies: Dict[str, deque] = {
            "market_data": deque(maxlen=1000),
            "ml_inference": deque(maxlen=1000),
            "trade_execution": deque(maxlen=1000),
            "feature_engineering": deque(maxlen=1000),
        }

    # --------------------------------------------------
    # Record events
    # --------------------------------------------------

    def record_request(self, path: str, status_code: int, latency_ms: float):
        self._requests.append(
            RequestMetric(
                path=path,
                status_code=status_code,
                latency_ms=latency_ms,
                timestamp=time.time(),
            )
        )

    def record_error(self, path: str, error: str):
        self._errors.append(
            {
                "path": path,
                "error": error,
                "timestamp": time.time(),
            }
        )

    def record_strategy_snapshot(self, strategy_data: dict):
        self._strategy_snapshots.append(
            {
                **strategy_data,
                "timestamp": time.time(),
            }
        )

    def record_risk_alert(self, alert: dict):
        self._risk_alerts.append(
            {
                **alert,
                "timestamp": time.time(),
            }
        )

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
            "pipeline_latency_ms": self._get_pipeline_latency(),
            "path_breakdown": dict(path_counts),
            "recent_errors": list(self._errors)[-10:],
            "strategy_snapshots": list(self._strategy_snapshots)[-5:],
            "risk_alerts": list(self._risk_alerts)[-10:],
        }

    # --------------------------------------------------
    # Pipeline latency tracking
    # --------------------------------------------------

    def record_market_data_latency(self, latency_ms: float):
        """Record market data fetch latency."""
        self._pipeline_latencies["market_data"].append(latency_ms)

    def record_ml_inference_latency(self, latency_ms: float):
        """Record ML model inference latency."""
        self._pipeline_latencies["ml_inference"].append(latency_ms)

    def record_trade_execution_latency(self, latency_ms: float):
        """Record trade execution latency."""
        self._pipeline_latencies["trade_execution"].append(latency_ms)

    def record_feature_engineering_latency(self, latency_ms: float):
        """Record feature engineering pipeline latency."""
        self._pipeline_latencies["feature_engineering"].append(latency_ms)

    def _get_pipeline_latency(self) -> Dict:
        """Get pipeline latency stats."""
        result = {}
        for name, latencies in self._pipeline_latencies.items():
            vals = list(latencies)
            if vals:
                result[name] = {
                    "avg": round(float(np.mean(vals)), 1),
                    "p95": round(float(np.percentile(vals, 95)), 1),
                    "count": len(vals),
                }
            else:
                result[name] = {"avg": 0, "p95": 0, "count": 0}
        return result
