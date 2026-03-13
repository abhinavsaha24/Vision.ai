"""
Enhanced regime detector combining rule-based and ML-based detection.
"""

from __future__ import annotations

import logging
import numpy as np
import pandas as pd
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class MarketRegimeDetector:
    """
    Market regime detection using rule-based + optional ML methods.

    Detects:
     - Trend direction (uptrend, downtrend, sideways)
     - Volatility regime (high_volatility, low_volatility)
     - Risk regime (risk_on, risk_off)
    """

    def __init__(self):
        self._hmm_detector = None

    def detect_volatility(self, df: pd.DataFrame) -> str:
        if "volatility_20" in df.columns:
            vol = df["volatility_20"].iloc[-1]
            avg_vol = df["volatility_20"].mean()
        elif "returns" in df.columns:
            vol = df["returns"].rolling(20).std().iloc[-1]
            avg_vol = df["returns"].rolling(20).std().mean()
        else:
            return "unknown"

        if vol > avg_vol * 1.5:
            return "high_volatility"
        elif vol > avg_vol:
            return "elevated_volatility"
        return "low_volatility"

    def detect_trend(self, df: pd.DataFrame) -> str:
        # Use ADX if available
        if "ADX" in df.columns:
            adx = df["ADX"].iloc[-1]
            if adx < 20:
                return "sideways"

        # EMA crossover
        if "EMA_12" in df.columns and "EMA_26" in df.columns:
            ema_short = df["EMA_12"].iloc[-1]
            ema_long = df["EMA_26"].iloc[-1]

            spread = (ema_short - ema_long) / (ema_long + 1e-8)

            if spread > 0.005:
                return "uptrend"
            elif spread < -0.005:
                return "downtrend"

        return "sideways"

    def detect_risk_regime(self, df: pd.DataFrame) -> str:
        """Risk-on vs Risk-off detection."""
        if "risk_regime_score" in df.columns:
            score = df["risk_regime_score"].iloc[-1]
            if score > 1.0:
                return "risk_on"
            elif score < -1.0:
                return "risk_off"
        return "neutral"

    def get_regime(self, df: pd.DataFrame) -> Dict:
        """Get comprehensive market regime."""
        trend = self.detect_trend(df)
        volatility = self.detect_volatility(df)
        risk = self.detect_risk_regime(df)

        # Composite regime label
        if trend in ("uptrend",) and volatility == "low_volatility":
            regime_label = "trending_calm"
        elif trend in ("downtrend",) and volatility == "high_volatility":
            regime_label = "crisis"
        elif trend == "sideways":
            regime_label = "range_bound"
        else:
            regime_label = "transitional"

        return {
            "trend": trend,
            "volatility": volatility,
            "risk": risk,
            "label": regime_label,
        }