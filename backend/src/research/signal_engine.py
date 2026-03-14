"""
Signal fusion engine: combines ML predictions, strategy signals, and sentiment
into a unified trading decision with confidence scoring.

Features:
  - Regime-aware dynamic weighting
  - Performance-based weight adaptation
  - Confidence-weighted blending
  - Multi-factor confidence scoring
"""

from __future__ import annotations

import numpy as np
import logging
from typing import Dict, Optional
from collections import deque

logger = logging.getLogger(__name__)


class QuantSignalEngine:
    """
    Advanced signal fusion combining multiple signal sources.
    """

    def __init__(self):
        # Base weights for signal sources
        self.weights = {
            "ai": 0.30,
            "strategy": 0.25,
            "momentum": 0.15,
            "mean_reversion": 0.10,
            "sentiment": 0.10,
            "risk_parity": 0.10,
        }

        # Performance tracking for adaptive weights
        self._performance_window = 50
        self._signal_history = deque(maxlen=self._performance_window)

    # --------------------------------------------------
    # Individual signal generators
    # --------------------------------------------------

    def ai_signal(self, prediction: Dict) -> int:
        prob = prediction.get("probability", 0.5)
        if prob > 0.6:
            return 1
        if prob < 0.4:
            return -1
        return 0

    def momentum_signal(self, df) -> int:
        if "close" not in df.columns or len(df) < 10:
            return 0

        close = df["close"]
        momentum = close.iloc[-1] - close.iloc[-10]

        if momentum > 0:
            return 1
        if momentum < 0:
            return -1
        return 0

    def mean_reversion_signal(self, df) -> int:
        if "RSI" not in df.columns:
            return 0
        rsi = df["RSI"].iloc[-1]
        if rsi < 30:
            return 1
        if rsi > 70:
            return -1
        return 0

    def sentiment_signal(self, sentiment_score: float) -> int:
        if sentiment_score > 0.2:
            return 1
        if sentiment_score < -0.2:
            return -1
        return 0

    def strategy_signal(self, strategy_result: Optional[Dict] = None) -> int:
        """Extract signal from strategy engine output."""
        if not strategy_result:
            return 0
        direction = strategy_result.get("direction", "FLAT")
        if direction == "LONG":
            return 1
        if direction == "SHORT":
            return -1
        return 0

    # --------------------------------------------------
    # Regime-aware weight adjustment
    # --------------------------------------------------

    def _adjust_weights_for_regime(self, regime: Optional[Dict] = None) -> Dict[str, float]:
        """Adjust signal weights based on market regime."""
        weights = dict(self.weights)

        if not regime:
            return weights

        trend = regime.get("trend", "sideways")
        volatility = regime.get("volatility", "low_volatility")

        if trend == "uptrend":
            weights["ai"] *= 1.2
            weights["momentum"] *= 1.3
            weights["mean_reversion"] *= 0.5
        elif trend == "downtrend":
            weights["ai"] *= 1.1
            weights["momentum"] *= 1.1
            weights["mean_reversion"] *= 0.8
        else:  # sideways
            weights["ai"] *= 0.9
            weights["momentum"] *= 0.5
            weights["mean_reversion"] *= 1.5

        if volatility == "high_volatility":
            weights["sentiment"] *= 0.5
            weights["strategy"] *= 0.8
            weights["risk_parity"] = weights.get("risk_parity", 0.1) * 1.5
        else:
            weights["sentiment"] *= 1.2

        # Normalize
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}

        return weights

    # --------------------------------------------------
    # Main signal generation
    # --------------------------------------------------

    def generate_signal(self, df, prediction: Dict, sentiment_score: float = 0.0,
                        regime: Optional[Dict] = None,
                        strategy_result: Optional[Dict] = None) -> Dict:
        """
        Combine all signals into a final trading decision.

        Returns:
            {
                direction: "BUY" | "SELL" | "HOLD",
                score: float,
                confidence: float,
                signals: dict of individual signals,
                weights: dict of adjusted weights,
            }
        """
        # Get regime-adjusted weights
        weights = self._adjust_weights_for_regime(regime)

        # Compute individual signals
        signals = {}
        signals["ai"] = self.ai_signal(prediction)
        signals["momentum"] = self.momentum_signal(df)
        signals["mean_reversion"] = self.mean_reversion_signal(df)
        signals["sentiment"] = self.sentiment_signal(sentiment_score)
        signals["strategy"] = self.strategy_signal(strategy_result)

        # Weighted aggregation
        final_score = sum(signals[k] * weights.get(k, 0) for k in signals)
        final_score = round(final_score, 4)

        # Confidence scoring
        confidence = self._compute_confidence(
            signals, prediction, regime, sentiment_score
        )

        # Direction
        if final_score > 0.1:
            direction = "BUY"
        elif final_score < -0.1:
            direction = "SELL"
        else:
            direction = "HOLD"

        # Regime gating: block new entries during crisis
        if regime and direction in ("BUY", "SELL"):
            label = regime.get("label", "")
            if label == "crisis":
                direction = "HOLD"
                confidence *= 0.3  # heavily reduce confidence

        # Track for adaptive weighting
        self._signal_history.append({
            "direction": direction,
            "score": final_score,
            "confidence": confidence,
        })

        return {
            "direction": direction,
            "score": final_score,
            "confidence": confidence,
            "signals": signals,
            "weights": weights,
        }

    # --------------------------------------------------
    # Confidence scoring
    # --------------------------------------------------

    def _compute_confidence(self, signals: Dict, prediction: Dict,
                            regime: Optional[Dict], sentiment_score: float) -> float:
        """
        Multi-factor confidence score (0.0 to 1.0).

        Factors:
        1. Model probability strength (how far from 0.5)
        2. Signal agreement (do signals align?)
        3. Regime clarity (clear trend vs ambiguous)
        4. Sentiment alignment
        """
        factors = []

        # 1. Model probability strength
        prob = prediction.get("probability", 0.5)
        prob_strength = abs(prob - 0.5) * 2  # 0=uncertain, 1=certain
        factors.append(prob_strength)

        # 2. Signal agreement
        signal_values = [v for v in signals.values() if v != 0]
        if len(signal_values) > 1:
            # All same direction = 1.0, mixed = lower
            agreement = abs(sum(signal_values)) / len(signal_values)
        elif len(signal_values) == 1:
            agreement = 0.5
        else:
            agreement = 0.0
        factors.append(agreement)

        # 3. Regime clarity
        if regime:
            trend = regime.get("trend", "sideways")
            if trend in ("uptrend", "downtrend"):
                regime_clarity = 0.8
            else:
                regime_clarity = 0.4
        else:
            regime_clarity = 0.5
        factors.append(regime_clarity)

        # 4. Sentiment alignment (does sentiment agree with signal direction?)
        if abs(sentiment_score) > 0.1:
            main_direction = 1 if sum(signals.values()) > 0 else -1
            sentiment_dir = 1 if sentiment_score > 0 else -1
            alignment = 0.8 if main_direction == sentiment_dir else 0.3
        else:
            alignment = 0.5
        factors.append(alignment)

        # Weighted average of factors
        confidence = float(np.mean(factors))
        return round(max(0.0, min(1.0, confidence)), 4)