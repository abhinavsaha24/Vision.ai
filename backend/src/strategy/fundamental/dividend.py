from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DividendSnapshot:
    dividend_yield: float
    payout_ratio: float
    dividend_cagr_5y: float
    free_cash_flow_coverage: float


class DividendStrategyEngine:
    def score(self, s: DividendSnapshot) -> dict[str, float]:
        yield_score = self._norm(s.dividend_yield, 0.01, 0.06)
        payout_score = 1.0 - self._norm(s.payout_ratio, 0.35, 1.2)
        growth_score = self._norm(s.dividend_cagr_5y, 0.0, 0.15)
        coverage_score = self._norm(s.free_cash_flow_coverage, 1.0, 2.5)

        sustainability = 0.45 * payout_score + 0.55 * coverage_score
        composite = 0.30 * yield_score + 0.35 * sustainability + 0.35 * growth_score

        return {
            "yield_score": round(yield_score, 4),
            "sustainability_score": round(sustainability, 4),
            "growth_score": round(growth_score, 4),
            "composite": round(composite, 4),
        }

    @staticmethod
    def _norm(value: float, low: float, high: float) -> float:
        if high <= low:
            return 0.0
        return max(0.0, min(1.0, (value - low) / (high - low)))
