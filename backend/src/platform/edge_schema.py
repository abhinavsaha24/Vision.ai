from __future__ import annotations

from typing import Any


REQUIRED_FIELDS = (
    "edge_id",
    "event_definition",
    "direction",
    "confidence_score",
    "expected_return",
    "holding_period",
    "regime",
    "asset_coverage",
    "sample_size",
    "in_sample_metrics",
    "out_of_sample_metrics",
    "decay_metrics",
)


class EdgeSchemaValidator:
    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def validate(edge: dict[str, Any]) -> tuple[bool, list[str]]:
        errors: list[str] = []
        for field in REQUIRED_FIELDS:
            if field not in edge:
                errors.append(f"missing:{field}")

        sample_size = EdgeSchemaValidator._safe_float(edge.get("sample_size", 0.0), 0.0)
        if sample_size < 200:
            errors.append("sample_size_too_small")

        oos = edge.get("out_of_sample_metrics", {}) or {}
        in_sample = edge.get("in_sample_metrics", {}) or {}
        oos_exp = EdgeSchemaValidator._safe_float(oos.get("expectancy", 0.0), 0.0)
        oos_t = EdgeSchemaValidator._safe_float(oos.get("t_stat", 0.0), 0.0)
        oos_pf = EdgeSchemaValidator._safe_float(oos.get("profit_factor", 0.0), 0.0)
        is_pf = EdgeSchemaValidator._safe_float(in_sample.get("profit_factor", 0.0), 0.0)

        if oos_exp <= 0.0:
            errors.append("unstable_oos_expectancy")
        if oos_t < 2.0:
            errors.append("weak_oos_significance")
        if oos_pf < 1.2:
            errors.append("weak_oos_profit_factor")
        if oos_pf > 10.0 and sample_size < 250:
            errors.append("oos_pf_anomaly")
        if oos_pf > 4.0 and sample_size < 400:
            errors.append("oos_pf_high_low_sample")
        if is_pf > 10.0 and sample_size < 250:
            errors.append("is_pf_anomaly")

        return len(errors) == 0, errors

    @classmethod
    def filter_edges(cls, edges: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for edge in edges:
            ok, reasons = cls.validate(edge)
            if ok:
                accepted.append(edge)
            else:
                rejected.append({"edge_id": edge.get("edge_id", "unknown"), "reason": reasons})
        return accepted, rejected
