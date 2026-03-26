from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import math


@dataclass
class AllocatorConfig:
    max_symbol_exposure: float = 0.30
    max_family_exposure: float = 0.40
    max_net_exposure: float = 0.35
    min_effective_weight: float = 1e-6


class EdgePortfolioAllocator:
    """Builds symbol-level target exposure from edge candidates under strict constraints."""

    def __init__(self, config: AllocatorConfig | None = None):
        self.config = config or AllocatorConfig()

    @staticmethod
    def _family(edge_id: str, fallback: str = "unknown") -> str:
        if not edge_id:
            return fallback
        return str(edge_id.split("|")[0])

    @staticmethod
    def _direction_sign(direction: str) -> float:
        d = str(direction).lower()
        if d == "long":
            return 1.0
        if d == "short":
            return -1.0
        return 0.0

    @staticmethod
    def _score(edge: dict[str, Any]) -> float:
        confidence = float(edge.get("confidence_score", 0.0) or 0.0)
        in_sample = edge.get("in_sample_metrics", {}) or edge.get("stats", {}) or {}
        t_stat = float(in_sample.get("t_stat", 0.0) or 0.0)
        sample_size = max(1.0, float(edge.get("sample_size", in_sample.get("samples", 1.0)) or 1.0))
        return max(0.0, confidence) * max(0.0, t_stat) * math.log(sample_size)

    def allocate(self, edges: list[dict[str, Any]]) -> dict[str, Any]:
        if not edges:
            return {"positions": {}, "meta": {"status": "no_edges"}}

        # Step 1: compute raw positive weights.
        scored: list[dict[str, Any]] = []
        for edge in edges:
            w = self._score(edge)
            if w <= self.config.min_effective_weight:
                continue
            scored.append({**edge, "raw_weight": w})

        if not scored:
            return {"positions": {}, "meta": {"status": "all_edges_below_weight_floor"}}

        total_raw = sum(float(x["raw_weight"]) for x in scored)
        for row in scored:
            row["weight"] = float(row["raw_weight"]) / max(total_raw, 1e-12)

        # Step 2: cap family concentration.
        family_sums: dict[str, float] = {}
        for row in scored:
            fam = self._family(str(row.get("edge_id", "")), str(row.get("event_definition", "unknown")))
            family_sums[fam] = family_sums.get(fam, 0.0) + float(row["weight"])

        for row in scored:
            fam = self._family(str(row.get("edge_id", "")), str(row.get("event_definition", "unknown")))
            fam_total = max(1e-12, family_sums.get(fam, 0.0))
            if fam_total > self.config.max_family_exposure:
                row["weight"] *= self.config.max_family_exposure / fam_total

        # Step 3: aggregate symbol directional exposure.
        symbol_signals: dict[str, list[float]] = {}
        for row in scored:
            direction = str(row.get("direction", ""))
            sign = self._direction_sign(direction)
            if sign == 0.0:
                continue
            assets = row.get("asset_coverage") or row.get("assets") or []
            if not assets:
                continue
            per_asset_weight = float(row["weight"]) / max(1, len(assets))
            for symbol in assets:
                symbol_signals.setdefault(str(symbol), []).append(sign * per_asset_weight)

        positions: dict[str, float] = {}
        for symbol, sigs in symbol_signals.items():
            pos_total = sum(1.0 for s in sigs if s > 0)
            neg_total = sum(1.0 for s in sigs if s < 0)
            conflict_penalty = 1.0
            if pos_total > 0 and neg_total > 0:
                # Conflict resolution: reduce exposure when edges disagree.
                conflict_penalty = max(0.2, abs(pos_total - neg_total) / (pos_total + neg_total))
            raw_symbol = sum(sigs) * conflict_penalty
            capped_symbol = max(-self.config.max_symbol_exposure, min(self.config.max_symbol_exposure, raw_symbol))
            positions[symbol] = float(capped_symbol)

        # Step 4: net exposure control (soft hedge by proportional scaling).
        net_exposure = sum(positions.values())
        if abs(net_exposure) > self.config.max_net_exposure and positions:
            scale = self.config.max_net_exposure / abs(net_exposure)
            for symbol in list(positions.keys()):
                positions[symbol] *= scale
            net_exposure = sum(positions.values())

        return {
            "positions": positions,
            "meta": {
                "status": "ok",
                "edge_count": len(scored),
                "net_exposure": float(net_exposure),
                "max_symbol_exposure": self.config.max_symbol_exposure,
                "max_family_exposure": self.config.max_family_exposure,
            },
        }
