"""
Prometheus-compatible metrics exporter.

Lightweight in-process metrics collection. Exposes counters, gauges, and
histograms in Prometheus text format via the /metrics endpoint.
"""

from __future__ import annotations

import time
import threading
from collections import defaultdict
from typing import Dict, List, Optional


class _Counter:
    __slots__ = ("_value", "_lock")

    def __init__(self) -> None:
        self._value = 0.0
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value += amount

    @property
    def value(self) -> float:
        return self._value


class _Gauge:
    __slots__ = ("_value", "_lock")

    def __init__(self) -> None:
        self._value = 0.0
        self._lock = threading.Lock()

    def set(self, value: float) -> None:
        with self._lock:
            self._value = value

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value += amount

    def dec(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value -= amount

    @property
    def value(self) -> float:
        return self._value


class _Histogram:
    __slots__ = ("_buckets", "_sum", "_count", "_lock", "_bounds")

    DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

    def __init__(self, buckets: Optional[tuple] = None) -> None:
        self._bounds = buckets or self.DEFAULT_BUCKETS
        self._buckets: Dict[float, int] = {b: 0 for b in self._bounds}
        self._sum = 0.0
        self._count = 0
        self._lock = threading.Lock()

    def observe(self, value: float) -> None:
        with self._lock:
            self._sum += value
            self._count += 1
            for bound in self._bounds:
                if value <= bound:
                    self._buckets[bound] += 1

    def snapshot(self) -> Dict:
        with self._lock:
            return {
                "buckets": dict(self._buckets),
                "sum": self._sum,
                "count": self._count,
            }


class MetricsRegistry:
    """Central registry for all application metrics."""

    def __init__(self) -> None:
        self._counters: Dict[str, _Counter] = {}
        self._gauges: Dict[str, _Gauge] = {}
        self._histograms: Dict[str, _Histogram] = {}
        self._labels: Dict[str, str] = {}  # metric_name -> help text
        self._lock = threading.Lock()

        # Pre-register standard metrics
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Pre-register standard application metrics."""
        self.counter("http_requests_total", "Total HTTP requests handled")
        self.counter("http_errors_total", "Total HTTP error responses")
        self.counter("ws_connections_total", "Total WebSocket connections opened")
        self.counter("ws_messages_sent_total", "Total WebSocket messages sent")
        self.counter("trades_executed_total", "Total trades executed")
        self.counter("trades_rejected_total", "Total trades rejected by risk controls")
        self.counter("kill_switch_activations_total", "Emergency kill switch activations")

        self.gauge("ws_active_connections", "Current active WebSocket connections")
        self.gauge("active_positions_count", "Number of currently open positions")
        self.gauge("portfolio_equity_usd", "Current portfolio equity in USD")
        self.gauge("portfolio_drawdown_pct", "Current drawdown percentage")
        self.gauge("uptime_seconds", "Server uptime in seconds")

        self.histogram("http_request_duration_seconds", "HTTP request latency")
        self.histogram("trade_execution_latency_seconds", "Trade execution latency")
        self.histogram("ws_message_latency_seconds", "WebSocket message processing latency")

    def counter(self, name: str, help_text: str = "") -> _Counter:
        with self._lock:
            if name not in self._counters:
                self._counters[name] = _Counter()
                self._labels[name] = help_text
            return self._counters[name]

    def gauge(self, name: str, help_text: str = "") -> _Gauge:
        with self._lock:
            if name not in self._gauges:
                self._gauges[name] = _Gauge()
                self._labels[name] = help_text
            return self._gauges[name]

    def histogram(self, name: str, help_text: str = "") -> _Histogram:
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = _Histogram()
                self._labels[name] = help_text
            return self._histograms[name]

    def export_text(self) -> str:
        """Export all metrics in Prometheus text exposition format."""
        lines: List[str] = []

        # Counters
        for name, counter in sorted(self._counters.items()):
            help_text = self._labels.get(name, "")
            if help_text:
                lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {counter.value}")

        # Gauges
        for name, gauge in sorted(self._gauges.items()):
            help_text = self._labels.get(name, "")
            if help_text:
                lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {gauge.value}")

        # Histograms
        for name, histogram in sorted(self._histograms.items()):
            help_text = self._labels.get(name, "")
            if help_text:
                lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} histogram")
            snap = histogram.snapshot()
            cumulative = 0
            for bound in sorted(snap["buckets"].keys()):
                cumulative += snap["buckets"][bound]
                lines.append(f'{name}_bucket{{le="{bound}"}} {cumulative}')
            lines.append(f'{name}_bucket{{le="+Inf"}} {snap["count"]}')
            lines.append(f"{name}_sum {snap['sum']}")
            lines.append(f"{name}_count {snap['count']}")

        lines.append("")
        return "\n".join(lines)

    def export_json(self) -> Dict:
        """Export metrics as a JSON-serializable dict."""
        result = {}
        for name, counter in self._counters.items():
            result[name] = {"type": "counter", "value": counter.value}
        for name, gauge in self._gauges.items():
            result[name] = {"type": "gauge", "value": gauge.value}
        for name, histogram in self._histograms.items():
            result[name] = {"type": "histogram", **histogram.snapshot()}
        return result


# Singleton instance
metrics = MetricsRegistry()
