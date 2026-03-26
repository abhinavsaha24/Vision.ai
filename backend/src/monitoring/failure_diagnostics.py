from __future__ import annotations

from typing import Any


OVER_CONCENTRATION_THRESHOLD = 0.30


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


class FailureDiagnostics:
    @staticmethod
    def analyze(
        edge_report: dict[str, Any],
        exposure_report: dict[str, Any],
        data_quality: dict[str, Any],
    ) -> dict[str, Any]:
        edge_report = edge_report or {}
        exposure_report = exposure_report or {}
        data_quality = data_quality or {}
        findings: list[dict[str, Any]] = []

        lifecycle = edge_report.get("lifecycle", {}) or {}
        shadow_edges = _safe_int(lifecycle.get("shadow_edges", 0), 0)
        retired_edges = _safe_int(lifecycle.get("retired_edges", 0), 0)
        if shadow_edges + retired_edges > 0:
            findings.append({
                "category": "edge_decay",
                "severity": "warning",
                "detail": f"shadow={shadow_edges} retired={retired_edges}",
                "action": "reduce capital and retrain registry",
            })

        net = _safe_float(exposure_report.get("net_exposure", 0.0), 0.0)
        if abs(net) > OVER_CONCENTRATION_THRESHOLD:
            findings.append({
                "category": "over_concentration",
                "severity": "warning",
                "detail": f"net_exposure={net:.4f}",
                "action": "tighten hedging and symbol caps",
            })

        missing_flow = _safe_int(data_quality.get("missing_flow_rows", 0), 0)
        if missing_flow > 0:
            findings.append({
                "category": "data_issues",
                "severity": "critical",
                "detail": f"missing_flow_rows={missing_flow}",
                "action": "repair flow ingestion before deployment",
            })

        return {
            "status": "ok" if not findings else "attention_required",
            "findings": findings,
        }
