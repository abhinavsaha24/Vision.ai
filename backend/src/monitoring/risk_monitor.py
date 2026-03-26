"""Risk health monitoring for drawdown, VaR and exposure limits."""

from __future__ import annotations

from typing import Dict


class RiskMonitor:
    def assess(self, state: Dict) -> Dict:
        drawdown = float(state.get("drawdown_pct", 0.0))
        var_breach = bool(state.get("var_breach", False))
        exposure_ok = bool(state.get("exposure_ok", True))

        status = "healthy"
        if drawdown > 0.08 or var_breach or not exposure_ok:
            status = "warning"
        if drawdown > 0.12 or (var_breach and not exposure_ok):
            status = "critical"

        return {
            "status": status,
            "drawdown_pct": drawdown,
            "var_breach": var_breach,
            "exposure_ok": exposure_ok,
        }
