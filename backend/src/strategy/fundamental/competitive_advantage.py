from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CompetitiveSnapshot:
    gross_margin: float
    operating_margin: float
    market_share_trend: float
    switching_cost_index: float
    network_effect_index: float


class CompetitiveAdvantageEngine:
    def score(self, s: CompetitiveSnapshot) -> dict[str, float]:
        margin_power = 0.55 * self._norm(s.gross_margin, 0.2, 0.7) + 0.45 * self._norm(s.operating_margin, 0.05, 0.4)
        structure = 0.40 * self._norm(s.market_share_trend, -0.05, 0.08) + 0.30 * self._norm(s.switching_cost_index, 0.0, 1.0) + 0.30 * self._norm(s.network_effect_index, 0.0, 1.0)
        composite = 0.6 * margin_power + 0.4 * structure
        return {
            "margin_power": round(margin_power, 4),
            "market_structure": round(structure, 4),
            "composite": round(composite, 4),
        }

    @staticmethod
    def _norm(value: float, low: float, high: float) -> float:
        if high <= low:
            return 0.0
        return max(0.0, min(1.0, (value - low) / (high - low)))
