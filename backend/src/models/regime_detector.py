"""
Market regime detector — research-backed implementation.

Based on: Hidden Markov Models for regime detection (Hamilton, 1989)

Model:
  Hidden state S_t ∈ {1,...,K} follows Markov chain with transition matrix P
  Returns | S_t=k ~ N(μ_k, σ_k²)
  Uses forward-backward algorithm to estimate P(S_t=k | r_{1:t})

Features:
  - HMM-based probabilistic regime detection (when hmmlearn available)
  - Rule-based fallback using EMA crossover + volatility thresholds
  - Regime-aware strategy gating (blocks entries in crisis regimes)
  - Composite labels: trending_calm, crisis, range_bound, transitional
"""

from __future__ import annotations

import logging
import numpy as np
import pandas as pd
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Attempt to load HMM library
_HMM_AVAILABLE = False
try:
    from hmmlearn.hmm import GaussianHMM
    _HMM_AVAILABLE = True
except ImportError:
    logger.info("hmmlearn not available — using rule-based regime detection only")


class MarketRegimeDetector:
    """
    Market regime detection using HMM + rule-based methods.

    Detects:
      - Trend direction (uptrend, downtrend, sideways)
      - Volatility regime (high_volatility, low_volatility, elevated_volatility)
      - Risk regime (risk_on, risk_off, neutral)
      - HMM state probabilities (when fitted)

    Parameters:
        n_regimes: number of HMM regimes (default 3: bull, bear, sideways)
        hmm_lookback: days of returns to use for HMM fitting
        vol_threshold: multiplier of mean vol for "high volatility"
        trend_threshold: EMA spread threshold for trend detection
    """

    def __init__(self, n_regimes: int = 3, hmm_lookback: int = 252,
                 vol_threshold: float = 1.5, trend_threshold: float = 0.005):
        self.n_regimes = n_regimes
        self.hmm_lookback = hmm_lookback
        self.vol_threshold = vol_threshold
        self.trend_threshold = trend_threshold
        self._hmm_model = None
        self._hmm_fitted = False
        self._regime_labels = {}  # state_id -> label mapping

    # --------------------------------------------------
    # HMM-Based Detection
    # --------------------------------------------------

    def fit_hmm(self, returns: np.ndarray) -> bool:
        """
        Fit Gaussian HMM on returns data.

        Returns True if fitting succeeded.
        """
        if not _HMM_AVAILABLE:
            return False

        try:
            data = returns.reshape(-1, 1)
            if len(data) < 50:
                return False

            model = GaussianHMM(
                n_components=self.n_regimes,
                covariance_type="diag",
                n_iter=100,
                random_state=42,
                tol=0.01,
            )
            model.fit(data)

            # Label regimes by mean return and variance
            means = model.means_.flatten()
            covs = model.covars_.flatten()

            # Sort by mean return to assign labels
            sorted_states = np.argsort(means)

            self._regime_labels = {}
            if self.n_regimes == 3:
                self._regime_labels[sorted_states[0]] = "bear"
                self._regime_labels[sorted_states[1]] = "sideways"
                self._regime_labels[sorted_states[2]] = "bull"
            elif self.n_regimes == 2:
                self._regime_labels[sorted_states[0]] = "bear"
                self._regime_labels[sorted_states[1]] = "bull"

            self._hmm_model = model
            self._hmm_fitted = True

            logger.info(
                f"HMM fitted: {self.n_regimes} regimes, "
                f"means={[round(float(m), 6) for m in means]}, "
                f"vars={[round(float(v), 6) for v in covs]}"
            )
            return True

        except Exception as e:
            logger.warning(f"HMM fitting failed: {e}")
            return False

    def predict_hmm_regime(self, returns: np.ndarray) -> Dict:
        """
        Predict current regime using fitted HMM.

        Returns dict with state probabilities and predicted state.
        """
        if not self._hmm_fitted or self._hmm_model is None:
            return {}

        try:
            data = returns.reshape(-1, 1)
            state_probs = self._hmm_model.predict_proba(data)
            current_probs = state_probs[-1]
            predicted_state = int(np.argmax(current_probs))

            return {
                "hmm_state": predicted_state,
                "hmm_label": self._regime_labels.get(predicted_state, "unknown"),
                "hmm_probabilities": {
                    self._regime_labels.get(i, f"state_{i}"): round(float(p), 4)
                    for i, p in enumerate(current_probs)
                },
                "hmm_confidence": round(float(current_probs[predicted_state]), 4),
            }

        except Exception as e:
            logger.warning(f"HMM prediction failed: {e}")
            return {}

    # --------------------------------------------------
    # Rule-Based Detection (Always Available)
    # --------------------------------------------------

    def detect_volatility(self, df: pd.DataFrame) -> str:
        """Detect volatility regime."""
        if "volatility_20" in df.columns:
            vol = df["volatility_20"].iloc[-1]
            avg_vol = df["volatility_20"].mean()
        elif "close" in df.columns and len(df) > 20:
            returns = df["close"].pct_change().dropna()
            vol = returns.iloc[-20:].std()
            avg_vol = returns.std()
        else:
            return "unknown"

        if vol > avg_vol * self.vol_threshold:
            return "high_volatility"
        elif vol > avg_vol:
            return "elevated_volatility"
        return "low_volatility"

    def detect_trend(self, df: pd.DataFrame) -> str:
        """Detect trend direction using EMA crossover."""
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

            if spread > self.trend_threshold:
                return "uptrend"
            elif spread < -self.trend_threshold:
                return "downtrend"

        # Fallback: simple price momentum
        if "close" in df.columns and len(df) >= 20:
            ret_20 = df["close"].iloc[-1] / df["close"].iloc[-20] - 1
            if ret_20 > 0.02:
                return "uptrend"
            elif ret_20 < -0.02:
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

    # --------------------------------------------------
    # Comprehensive Regime Detection
    # --------------------------------------------------

    def get_regime(self, df: pd.DataFrame) -> Dict:
        """
        Get comprehensive market regime combining HMM and rule-based.

        Returns:
            dict with trend, volatility, risk, label, and HMM data
        """
        trend = self.detect_trend(df)
        volatility = self.detect_volatility(df)
        risk = self.detect_risk_regime(df)

        # Try HMM prediction
        hmm_data = {}
        if self._hmm_fitted and "close" in df.columns and len(df) > 20:
            try:
                returns = df["close"].pct_change().dropna().values
                if len(returns) > 20:
                    hmm_data = self.predict_hmm_regime(returns[-self.hmm_lookback:])
            except Exception:
                pass

        # If no HMM fitted yet, try to fit
        if not self._hmm_fitted and "close" in df.columns and len(df) > 100:
            try:
                returns = df["close"].pct_change().dropna().values
                self.fit_hmm(returns)
                if self._hmm_fitted:
                    hmm_data = self.predict_hmm_regime(returns[-self.hmm_lookback:])
            except Exception:
                pass

        # Composite regime label
        if trend == "uptrend" and volatility == "low_volatility":
            regime_label = "trending_calm"
        elif trend == "downtrend" and volatility in ("high_volatility", "elevated_volatility"):
            regime_label = "crisis"
        elif trend == "sideways":
            regime_label = "range_bound"
        elif volatility == "high_volatility":
            regime_label = "volatile"
        else:
            regime_label = "transitional"

        result = {
            "trend": trend,
            "volatility": volatility,
            "risk": risk,
            "label": regime_label,
        }
        result.update(hmm_data)

        return result

    def should_allow_entries(self, regime: Dict, min_confidence: float = 0.6) -> bool:
        """
        Regime-aware gating: should we allow new trade entries?

        Blocks entries in crisis regimes or when HMM confidence
        in a "good" state is low.
        """
        label = regime.get("label", "")

        # Block new entries during crisis
        if label == "crisis":
            return False

        # If HMM is available, check bull/sideways probability
        hmm_probs = regime.get("hmm_probabilities", {})
        if hmm_probs:
            good_prob = hmm_probs.get("bull", 0) + hmm_probs.get("sideways", 0)
            if good_prob < min_confidence:
                return False

        return True