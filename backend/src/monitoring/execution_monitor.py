"""Execution quality monitoring and alerts."""

from __future__ import annotations

from typing import Dict


class ExecutionMonitor:
    def assess(self, fill_stats: Dict) -> Dict:
        avg_latency_ms = float(fill_stats.get("avg_latency_ms", 0.0))
        avg_slippage_bps = float(fill_stats.get("avg_slippage_bps", 0.0))

        quality = "good"
        if avg_latency_ms > 800 or avg_slippage_bps > 20:
            quality = "degraded"
        if avg_latency_ms > 1500 or avg_slippage_bps > 40:
            quality = "critical"

        return {
            "quality": quality,
            "avg_latency_ms": avg_latency_ms,
            "avg_slippage_bps": avg_slippage_bps,
            "alerts": [
                "latency_high" if avg_latency_ms > 800 else None,
                "slippage_high" if avg_slippage_bps > 20 else None,
            ],
        }
