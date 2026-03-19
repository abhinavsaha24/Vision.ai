"""Institutional portfolio optimizer wrapper with hard risk constraints."""

from __future__ import annotations

from typing import Dict

from backend.src.portfolio.optimizer import PortfolioOptimizer


class InstitutionalPortfolioOptimizer:
    def __init__(self, max_weight: float = 0.25, min_weight: float = 0.0):
        self.max_weight = max_weight
        self.min_weight = min_weight
        self.base = PortfolioOptimizer()

    def optimize(self, returns, method: str = "risk_parity") -> Dict:
        result = self.base.optimize(returns, method=method)
        weights = result.get("weights", {})
        clipped = {}
        total = 0.0
        for k, v in weights.items():
            w = min(self.max_weight, max(self.min_weight, float(v)))
            clipped[k] = w
            total += w

        if total > 0:
            clipped = {k: v / total for k, v in clipped.items()}

        result["weights"] = clipped
        result["institutional_constraints"] = {
            "max_weight": self.max_weight,
            "min_weight": self.min_weight,
        }
        return result
