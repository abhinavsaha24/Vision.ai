from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MacroSnapshot:
    real_rate: float
    inflation_yoy: float
    gdp_growth_yoy: float
    credit_spread: float
    sector_momentum: float


class MacroEngine:
    def score(self, s: MacroSnapshot) -> dict[str, float]:
        growth = self._norm(s.gdp_growth_yoy, -0.02, 0.05)
        inflation = 1.0 - self._norm(s.inflation_yoy, 0.015, 0.08)
        rates = 1.0 - self._norm(s.real_rate, 0.0, 0.04)
        credit = 1.0 - self._norm(s.credit_spread, 0.01, 0.08)
        rotation = self._norm(s.sector_momentum, -0.1, 0.2)

        risk_on = 0.30 * growth + 0.20 * inflation + 0.20 * rates + 0.15 * credit + 0.15 * rotation
        return {
            "growth_score": round(growth, 4),
            "inflation_score": round(inflation, 4),
            "rates_score": round(rates, 4),
            "credit_score": round(credit, 4),
            "rotation_score": round(rotation, 4),
            "risk_on_score": round(risk_on, 4),
        }

    @staticmethod
    def _norm(value: float, low: float, high: float) -> float:
        if high <= low:
            return 0.0
        return max(0.0, min(1.0, (value - low) / (high - low)))
