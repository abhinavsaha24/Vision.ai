"""
Risk score calculator for API responses.
"""

from __future__ import annotations

from typing import Dict

import numpy as np


class RiskScore:
    """Calculate composite risk score for the current market."""

    def calculate_risk(self, df) -> Dict:
        """
        Compute a composite risk score from market data.

        Returns:
            {risk_level, risk_score, factors}
        """
        factors = {}
        scores = []

        if df is None or df.empty:
            return {
                "risk_level": "medium",
                "risk_score": 0.5,
                "factors": {"error": "no data"},
            }

        # Volatility factor
        if "volatility_20" in df.columns:
            vol = float(df["volatility_20"].iloc[-1])
            vol_median = float(df["volatility_20"].median())
            vol_score = min(1.0, vol / (vol_median + 1e-8))
            factors["volatility"] = round(vol_score, 4)
            scores.append(vol_score)

        # RSI extremes
        if "RSI" in df.columns:
            rsi = float(df["RSI"].iloc[-1])
            rsi_risk = 0.0
            if rsi > 80 or rsi < 20:
                rsi_risk = 0.8
            elif rsi > 70 or rsi < 30:
                rsi_risk = 0.4
            factors["rsi_extreme"] = rsi_risk
            scores.append(rsi_risk)

        # Drawdown factor
        if "close" in df.columns and len(df) > 20:
            peak = float(df["close"].iloc[-20:].max())
            current = float(df["close"].iloc[-1])
            dd = (peak - current) / peak if peak > 0 else 0
            factors["recent_drawdown"] = round(dd, 4)
            scores.append(min(1.0, dd * 5))  # scale: 20% dd = 1.0

        # ADX trend strength
        if "ADX" in df.columns:
            adx = float(df["ADX"].iloc[-1])
            # Low ADX = no trend = higher risk
            adx_risk = max(0.0, 1.0 - adx / 50)
            factors["trend_weakness"] = round(adx_risk, 4)
            scores.append(adx_risk)

        # VaR estimate
        if "returns" in df.columns and len(df) > 30:
            returns = df["returns"].dropna().values
            var_95 = float(np.percentile(returns, 5))
            factors["var_95"] = round(abs(var_95), 6)
            scores.append(min(1.0, abs(var_95) * 20))

        # Composite score
        risk_score = float(np.mean(scores)) if scores else 0.5

        if risk_score > 0.7:
            risk_level = "high"
        elif risk_score > 0.4:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "risk_level": risk_level,
            "risk_score": round(risk_score, 4),
            "factors": factors,
        }
