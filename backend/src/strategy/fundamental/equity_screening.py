from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EquityMetrics:
    pe_ratio: float
    revenue_growth_yoy: float
    debt_to_equity: float
    gross_margin: float
    roic: float


class EquityScreeningEngine:
    """Scores fundamental quality for equity candidate ranking."""

    def score(self, m: EquityMetrics) -> dict[str, float]:
        value_score = self._value_score(m.pe_ratio)
        growth_score = self._bounded_linear(m.revenue_growth_yoy, 0.0, 0.25)
        debt_score = 1.0 - self._bounded_linear(m.debt_to_equity, 0.2, 1.5)
        moat_score = 0.6 * self._bounded_linear(m.gross_margin, 0.2, 0.7) + 0.4 * self._bounded_linear(m.roic, 0.05, 0.25)

        composite = (
            0.25 * value_score
            + 0.30 * growth_score
            + 0.20 * debt_score
            + 0.25 * moat_score
        )

        return {
            "value_score": round(value_score, 4),
            "growth_score": round(growth_score, 4),
            "debt_score": round(debt_score, 4),
            "moat_score": round(moat_score, 4),
            "composite": round(composite, 4),
        }

    @staticmethod
    def _value_score(pe_ratio: float) -> float:
        if pe_ratio <= 0:
            return 0.0
        return max(0.0, min(1.0, 1.0 - ((pe_ratio - 8.0) / 32.0)))

    @staticmethod
    def _bounded_linear(value: float, low: float, high: float) -> float:
        if high <= low:
            return 0.0
        return max(0.0, min(1.0, (value - low) / (high - low)))
