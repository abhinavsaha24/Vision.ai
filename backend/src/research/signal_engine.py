"""
Signal fusion engine v2: alpha-feature-driven signal pipeline.

Replaces the old RSI/MACD/momentum approach with signals derived from
research-grade alpha features (order flow, microstructure, regime, stats).

Design:
  - All signals are derived from alpha features (of_, vi_, rg_, st_ prefixes)
  - No weak indicators (RSI, MACD) used for signal generation
  - Regime-aware dynamic weighting
  - Confidence scoring from signal agreement + model probability
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class QuantSignalEngine:
    """
    Alpha-feature-driven signal fusion engine.

    Signal sources (all derived from alpha features):
      1. AI model probability (primary)
      2. Order flow (volume delta z-score, OB imbalance)
      3. Volume intelligence (smart money flow, volume-weighted momentum)
      4. Volatility breakout (vol term structure, regime change)
      5. Momentum quality (Sharpe of returns, cross-TF agreement)
      6. Sentiment (external sentiment score)
    """

    def __init__(self):
        # Signal source weights -- AI model is dominant
        self.weights = {
            "ai": 0.35,
            "order_flow": 0.20,
            "volume_intel": 0.15,
            "vol_breakout": 0.10,
            "momentum_quality": 0.10,
            "sentiment": 0.10,
        }

        # Performance tracking for adaptive weights
        self._performance_window = 50
        self._signal_history: deque = deque(maxlen=self._performance_window)

    # --------------------------------------------------
    # Individual signal generators (alpha-feature-based)
    # --------------------------------------------------

    def ai_signal(self, prediction: Dict) -> int:
        """Primary signal from AlphaModel probability."""
        prob = prediction.get("probability", 0.5)
        if prob > 0.60:
            return 1
        if prob < 0.40:
            return -1
        return 0

    def order_flow_signal(self, df: pd.DataFrame) -> int:
        """
        Order flow signal from volume delta z-score and OB imbalance.
        Replaces the old RSI-based mean reversion signal.
        """
        score = 0.0

        # Volume delta z-score (strongest microstructure signal)
        if "of_volume_delta_zscore" in df.columns:
            vd = float(df["of_volume_delta_zscore"].iloc[-1])
            if abs(vd) > 1.5:
                score += np.sign(vd) * 0.5
            elif abs(vd) > 0.8:
                score += np.sign(vd) * 0.25

        # Order book imbalance
        if "of_ob_imbalance" in df.columns:
            obi = float(df["of_ob_imbalance"].iloc[-1])
            if abs(obi) > 0.3:
                score += np.sign(obi) * 0.3

        # Cumulative volume delta trend
        if "of_cvd_20" in df.columns:
            cvd = float(df["of_cvd_20"].iloc[-1])
            cvd_norm = np.clip(cvd / (abs(cvd) + 1e-8), -1, 1)
            score += cvd_norm * 0.2

        if score > 0.3:
            return 1
        if score < -0.3:
            return -1
        return 0

    def volume_intel_signal(self, df: pd.DataFrame) -> int:
        """
        Volume intelligence signal from smart money flow and volume-weighted
        momentum. Replaces the old raw price momentum signal.
        """
        score = 0.0

        # Smart money flow (top-20% volume bars directional bias)
        if "vi_smart_money_flow" in df.columns:
            smf = float(df["vi_smart_money_flow"].iloc[-1])
            score += np.clip(smf * 3.0, -0.5, 0.5)

        # Volume-weighted momentum (actual alpha over price-only momentum)
        if "vi_vw_momentum_10" in df.columns:
            vwm = float(df["vi_vw_momentum_10"].iloc[-1])
            score += np.clip(vwm * 5.0, -0.5, 0.5)

        if score > 0.3:
            return 1
        if score < -0.3:
            return -1
        return 0

    def vol_breakout_signal(self, df: pd.DataFrame) -> int:
        """
        Volatility breakout signal from vol term structure and regime change.
        Detects when short-term vol expands vs long-term (breakout imminent).
        """
        score = 0.0

        # Vol term structure: short-term vol / long-term vol
        # Ratio > 1.5 = short-term vol spike = breakout
        if "rg_vol_term_5_20" in df.columns:
            vt = float(df["rg_vol_term_5_20"].iloc[-1])
            if vt > 1.5:
                # Breakout detected -- use recent momentum direction
                if "rg_tf_agreement" in df.columns:
                    tfa = float(df["rg_tf_agreement"].iloc[-1])
                    score += np.sign(tfa) * 0.6
                else:
                    score += 0.3  # Bias long during breakouts without direction

        # Regime change detector (sudden vol shift)
        if "rg_vol_regime_change" in df.columns:
            rc = float(df["rg_vol_regime_change"].iloc[-1])
            if rc > 0.5:  # Large regime change
                # Stay flat during rapid regime transitions
                return 0

        if score > 0.2:
            return 1
        if score < -0.2:
            return -1
        return 0

    def momentum_quality_signal(self, df: pd.DataFrame) -> int:
        """
        Momentum quality signal: only trade momentum when it has a positive
        Sharpe ratio and cross-timeframe agreement.
        """
        score = 0.0

        # Momentum Sharpe (is recent momentum statistically significant?)
        if "st_momentum_sharpe_10" in df.columns:
            ms = float(df["st_momentum_sharpe_10"].iloc[-1])
            if abs(ms) > 0.5:
                score += np.sign(ms) * 0.4

        # Cross-timeframe agreement (5/20/50 bar momentum agree?)
        if "rg_tf_agreement" in df.columns:
            tfa = float(df["rg_tf_agreement"].iloc[-1])
            if abs(tfa) > 0.5:
                score += np.sign(tfa) * 0.3

        # Market efficiency (trending vs noise)
        if "rg_efficiency_20" in df.columns:
            eff = float(df["rg_efficiency_20"].iloc[-1])
            if eff > 0.4:  # High efficiency = trending market
                score *= 1.5  # Amplify momentum signal

        if score > 0.25:
            return 1
        if score < -0.25:
            return -1
        return 0

    def sentiment_signal(self, sentiment_score: float) -> int:
        """Sentiment signal from external data (CryptoPanic, news, social)."""
        if sentiment_score > 0.2:
            return 1
        if sentiment_score < -0.2:
            return -1
        return 0

    # --------------------------------------------------
    # Regime-aware weight adjustment
    # --------------------------------------------------

    def _adjust_weights_for_regime(
        self, regime: Optional[Dict] = None
    ) -> Dict[str, float]:
        """Adjust signal weights based on market regime."""
        weights = dict(self.weights)

        if not regime:
            return weights

        trend = regime.get("trend", "sideways")
        volatility = regime.get("volatility", "low_volatility")

        if trend == "uptrend":
            weights["ai"] *= 1.2
            weights["momentum_quality"] *= 1.4
            weights["order_flow"] *= 1.1
            weights["vol_breakout"] *= 0.7
        elif trend == "downtrend":
            weights["ai"] *= 1.1
            weights["order_flow"] *= 1.3
            weights["momentum_quality"] *= 1.0
            weights["vol_breakout"] *= 0.8
        else:  # sideways
            weights["ai"] *= 0.9
            weights["order_flow"] *= 1.2
            weights["momentum_quality"] *= 0.5
            weights["vol_breakout"] *= 1.3

        if volatility == "high_volatility":
            weights["sentiment"] *= 0.4  # Sentiment is noise in high vol
            weights["vol_breakout"] *= 1.5
            weights["order_flow"] *= 1.2
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

    def generate_signal(
        self,
        df: pd.DataFrame,
        prediction: Dict,
        sentiment_score: float = 0.0,
        regime: Optional[Dict] = None,
        strategy_result: Optional[Dict] = None,
    ) -> Dict:
        """
        Combine all alpha-feature signals into a final trading decision.

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

        # Compute individual signals (all from alpha features)
        signals = {}
        signals["ai"] = self.ai_signal(prediction)
        signals["order_flow"] = self.order_flow_signal(df)
        signals["volume_intel"] = self.volume_intel_signal(df)
        signals["vol_breakout"] = self.vol_breakout_signal(df)
        signals["momentum_quality"] = self.momentum_quality_signal(df)
        signals["sentiment"] = self.sentiment_signal(sentiment_score)

        # Weighted aggregation
        final_score = sum(signals[k] * weights.get(k, 0) for k in signals)
        final_score = round(final_score, 4)

        # Confidence scoring
        confidence = self._compute_confidence(
            signals, prediction, regime, sentiment_score
        )

        # Direction
        if final_score > 0.15:
            direction = "BUY"
        elif final_score < -0.15:
            direction = "SELL"
        else:
            direction = "HOLD"

        # Regime gating: block new entries during crisis
        if regime and direction in ("BUY", "SELL"):
            label = regime.get("label", "")
            if label == "crisis":
                direction = "HOLD"
                confidence *= 0.3

        # Track for monitoring
        self._signal_history.append(
            {
                "direction": direction,
                "score": final_score,
                "confidence": confidence,
            }
        )

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

    def _compute_confidence(
        self,
        signals: Dict,
        prediction: Dict,
        regime: Optional[Dict],
        sentiment_score: float,
    ) -> float:
        """
        Multi-factor confidence score (0.0 to 1.0).

        Factors:
        1. Model probability strength (how far from 0.5)
        2. Signal agreement (do alpha signals align?)
        3. Regime clarity (clear trend vs ambiguous)
        4. Order flow confirmation
        """
        factors = []

        # 1. Model probability strength
        prob = prediction.get("probability", 0.5)
        prob_strength = abs(prob - 0.5) * 2  # 0=uncertain, 1=certain
        factors.append(prob_strength)

        # 2. Signal agreement (unanimous = high confidence)
        signal_values = [v for v in signals.values() if v != 0]
        if len(signal_values) > 1:
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

        # 4. Sentiment alignment
        if abs(sentiment_score) > 0.1:
            main_direction = 1 if sum(signals.values()) > 0 else -1
            sentiment_dir = 1 if sentiment_score > 0 else -1
            alignment = 0.8 if main_direction == sentiment_dir else 0.3
        else:
            alignment = 0.5
        factors.append(alignment)

        confidence = float(np.mean(factors))
        return round(max(0.0, min(1.0, confidence)), 4)

    # --------------------------------------------------
    # Backward compatibility
    # --------------------------------------------------

    def get_latest_signal(self, symbol: str = "BTCUSDT") -> Optional[Dict]:
        """Return the most recent signal for a symbol."""
        if self._signal_history:
            return dict(self._signal_history[-1])
        return None
