"""Live trading guardrail policy manager."""

from __future__ import annotations

from typing import Dict, List


class LiveGuard:
    def evaluate(
        self, readiness: Dict, risk_status: Dict, execution_status: Dict
    ) -> Dict:
        reasons: List[str] = []
        if not readiness.get("all_ready", False):
            reasons.append("readiness_failed")
        if risk_status.get("status") == "critical":
            reasons.append("risk_critical")
        if execution_status.get("quality") == "critical":
            reasons.append("execution_critical")

        return {
            "allow_live": len(reasons) == 0,
            "blocked_reasons": reasons,
        }
