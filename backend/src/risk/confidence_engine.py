"""
Confidence engine: multi-factor confidence scoring for trading decisions.
"""

from __future__ import annotations

from typing import Dict, Optional



class ConfidenceEngine:
    """
    Calculates a composite confidence score from multiple factors.
    """

    def __init__(self):
        self.factor_weights = {
            "probability_strength": 0.30,
            "model_agreement": 0.25,
            "regime_clarity": 0.20,
            "recent_performance": 0.15,
            "volatility_favorability": 0.10,
        }

    def calculate_confidence(
        self,
        probability: float,
        model_agreement: float = 1.0,
        regime: Optional[Dict] = None,
        recent_win_rate: float = 0.5,
        volatility_regime: str = "low_volatility",
    ) -> float:
        """
        Multi-factor confidence score.

        Args:
            probability: ML model probability (0-1)
            model_agreement: how much individual models agree (0-1)
            regime: market regime dict
            recent_win_rate: recent strategy win rate
            volatility_regime: "low_volatility" or "high_volatility"

        Returns:
            Confidence score 0.0 to 1.0
        """
        factors = {}

        # Probability strength (distance from 0.5)
        factors["probability_strength"] = abs(probability - 0.5) * 2

        # Model agreement
        factors["model_agreement"] = max(0.0, min(1.0, model_agreement))

        # Regime clarity
        if regime:
            trend = regime.get("trend", "sideways")
            if trend in ("uptrend", "downtrend"):
                factors["regime_clarity"] = 0.8
            else:
                factors["regime_clarity"] = 0.4
        else:
            factors["regime_clarity"] = 0.5

        # Recent performance
        factors["recent_performance"] = max(0.0, min(1.0, recent_win_rate))

        # Volatility favorability (lower vol = more predictable)
        if volatility_regime == "high_volatility":
            factors["volatility_favorability"] = 0.3
        else:
            factors["volatility_favorability"] = 0.7

        # Weighted average
        score = sum(factors[k] * self.factor_weights.get(k, 0) for k in factors)

        return round(max(0.0, min(1.0, score)), 4)
