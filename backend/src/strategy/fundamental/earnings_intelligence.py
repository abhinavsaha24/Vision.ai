from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EarningsSnapshot:
    eps_estimate: float
    eps_actual: float
    revenue_estimate: float
    revenue_actual: float
    guidance_delta_pct: float


class EarningsIntelligenceEngine:
    def score(self, s: EarningsSnapshot) -> dict[str, float]:
        eps_surprise = self._pct_delta(s.eps_actual, s.eps_estimate)
        rev_surprise = self._pct_delta(s.revenue_actual, s.revenue_estimate)
        guidance = s.guidance_delta_pct

        composite = 0.45 * self._norm(eps_surprise, -0.15, 0.15) + 0.35 * self._norm(rev_surprise, -0.10, 0.10) + 0.20 * self._norm(guidance, -0.10, 0.10)

        return {
            "eps_surprise_pct": round(eps_surprise, 4),
            "revenue_surprise_pct": round(rev_surprise, 4),
            "guidance_delta_pct": round(guidance, 4),
            "composite": round(composite, 4),
        }

    @staticmethod
    def _pct_delta(actual: float, estimate: float) -> float:
        denom = abs(estimate) if abs(estimate) > 1e-9 else 1.0
        return (actual - estimate) / denom

    @staticmethod
    def _norm(value: float, low: float, high: float) -> float:
        if high <= low:
            return 0.0
        return max(0.0, min(1.0, (value - low) / (high - low)))
