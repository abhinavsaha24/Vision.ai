"""
Health monitoring for production trading systems.

Reports component-level health status:
  - Exchange connectivity
  - Model availability
  - Data freshness
  - Trading loop heartbeat
  - Risk manager state
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Dict

logger = logging.getLogger(__name__)


class HealthMonitor:
    """
    Component health monitor.

    Tracks the health of each subsystem and exposes a unified status.
    Designed to be called by /health/detailed API endpoint.
    """

    def __init__(self):
        self.start_time = time.time()
        self._component_status: Dict[str, Dict] = {}

    def _uptime(self) -> float:
        return round(time.time() - self.start_time, 1)

    def update_component(
        self, name: str, healthy: bool, message: str = "", latency_ms: float = 0.0
    ):
        """Update a component's health status."""
        self._component_status[name] = {
            "healthy": healthy,
            "message": message,
            "latency_ms": round(latency_ms, 1),
            "last_check": datetime.now(timezone.utc).isoformat(),
        }

    def check_all(
        self,
        predictor=None,
        paper_trader=None,
        risk_manager=None,
        cached_df=None,
        last_data_update: float = 0,
    ) -> Dict:
        """
        Run all health checks and return unified status.

        Args:
            predictor: Predictor instance (or None)
            paper_trader: TradingLoop instance (or None)
            risk_manager: RiskManager instance
            cached_df: Cached market data DataFrame
            last_data_update: Timestamp of last data refresh
        """
        components = {}

        # 1. API
        components["api"] = {
            "healthy": True,
            "message": "API responding",
            "uptime_seconds": self._uptime(),
        }

        # 2. ML Predictor
        if predictor is not None:
            components["predictor"] = {
                "healthy": True,
                "message": "Model loaded and ready",
            }
        else:
            components["predictor"] = {
                "healthy": False,
                "message": "Predictor not loaded — predictions unavailable",
            }

        # 3. Market data freshness
        if cached_df is not None and last_data_update > 0:
            age = time.time() - last_data_update
            fresh = age < 120  # data older than 2 min = stale
            components["market_data"] = {
                "healthy": fresh,
                "message": f"Data age: {age:.0f}s {'(fresh)' if fresh else '(STALE)'}",
                "rows": len(cached_df),
            }
        else:
            components["market_data"] = {
                "healthy": False,
                "message": "No cached market data",
            }

        # 4. Trading loop
        if paper_trader is not None:
            heartbeat_age = time.time() - getattr(paper_trader, "last_heartbeat", 0)
            running = getattr(paper_trader, "running", False)
            components["trading_loop"] = {
                "healthy": running,
                "message": (
                    f"Running (cycle {paper_trader.cycle_count}, "
                    f"heartbeat {heartbeat_age:.0f}s ago)"
                    if running
                    else "Not running"
                ),
                "mode": getattr(paper_trader, "mode", "paper"),
                "errors": getattr(paper_trader, "consecutive_errors", 0),
            }
        else:
            components["trading_loop"] = {
                "healthy": True,  # Not running is OK
                "message": "Not initialized",
            }

        # 5. Risk manager
        if risk_manager is not None:
            kill_active = risk_manager.kill_switch_active
            components["risk_manager"] = {
                "healthy": not kill_active,
                "message": "KILL SWITCH ACTIVE" if kill_active else "Normal",
                "kill_switch": kill_active,
                "recent_events": len(risk_manager.events),
            }
        else:
            components["risk_manager"] = {
                "healthy": False,
                "message": "Risk manager not initialized",
            }

        # Merge with manually updated component statuses
        components.update(self._component_status)

        # Overall health
        all_healthy = all(c.get("healthy", False) for c in components.values())

        return {
            "status": "healthy" if all_healthy else "degraded",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime_seconds": self._uptime(),
            "components": components,
        }
