"""
Regime detection models using statistical methods.

Models:
  - HMMRegimeDetector: Hidden Markov Model for identifying market regimes
  - GMMRegimeDetector: Gaussian Mixture Model for return clustering

Falls back gracefully if hmmlearn is not installed.
"""

from __future__ import annotations

import logging
import numpy as np
import pandas as pd
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Check library availability
# ------------------------------------------------------------------

_HAS_HMM = False
try:
    from hmmlearn.hmm import GaussianHMM
    _HAS_HMM = True
except ImportError:
    logger.warning("hmmlearn not installed — HMM regime detector unavailable")

_HAS_GMM = True  # sklearn is always available
from sklearn.mixture import GaussianMixture


# ==================================================================
# Regime labels
# ==================================================================

REGIME_LABELS = {
    0: "low_vol_trending",
    1: "high_vol_trending",
    2: "mean_reverting",
    3: "crisis",
}


def _label_regimes(means: np.ndarray, covars: np.ndarray, n_states: int) -> Dict[int, str]:
    """Assign descriptive labels based on state means/variances."""
    labels = {}
    vols = np.sqrt(covars.flatten()[:n_states]) if covars.ndim > 1 else np.sqrt(covars[:n_states])
    ret_means = means.flatten()[:n_states]

    # Sort states by volatility
    vol_order = np.argsort(vols)

    for rank, state_idx in enumerate(vol_order):
        m = ret_means[state_idx]
        v = vols[state_idx]

        if rank == 0:  # lowest vol
            labels[state_idx] = "low_volatility"
        elif rank == n_states - 1:  # highest vol
            if m < 0:
                labels[state_idx] = "crisis"
            else:
                labels[state_idx] = "high_volatility"
        else:
            if abs(m) < v * 0.5:
                labels[state_idx] = "mean_reverting"
            else:
                labels[state_idx] = "trending"

    return labels


# ==================================================================
# HMM Regime Detector
# ==================================================================

class HMMRegimeDetector:
    """Hidden Markov Model for market regime detection."""

    def __init__(self, n_states: int = 3, n_iter: int = 100, random_state: int = 42):
        if not _HAS_HMM:
            raise ImportError("hmmlearn is required for HMMRegimeDetector. Install: pip install hmmlearn")

        self.n_states = n_states
        self.n_iter = n_iter
        self.random_state = random_state
        self.model = None
        self.labels = {}

    def fit(self, df: pd.DataFrame) -> "HMMRegimeDetector":
        """
        Fit HMM on returns and volatility features.

        Args:
            df: DataFrame with 'returns' and 'volatility_20' columns
        """
        features = self._extract_features(df)

        self.model = GaussianHMM(
            n_components=self.n_states,
            covariance_type="full",
            n_iter=self.n_iter,
            random_state=self.random_state,
        )
        self.model.fit(features)

        # Generate labels based on learned parameters
        self.labels = _label_regimes(
            self.model.means_,
            np.array([c[0, 0] for c in self.model.covars_]),
            self.n_states
        )

        logger.info(f"HMM fitted — {self.n_states} states, labels: {self.labels}")
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        """Return regime state index for each row."""
        if self.model is None:
            raise RuntimeError("HMM not fitted — call .fit() first")

        features = self._extract_features(df)
        return self.model.predict(features)

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        """Return posterior probabilities for each regime."""
        if self.model is None:
            raise RuntimeError("HMM not fitted — call .fit() first")

        features = self._extract_features(df)
        return self.model.predict_proba(features)

    def get_current_regime(self, df: pd.DataFrame) -> Dict:
        """Get regime for the most recent observation."""
        states = self.predict(df)
        probas = self.predict_proba(df)

        current_state = int(states[-1])
        current_proba = probas[-1]

        return {
            "regime_id": current_state,
            "regime_label": self.labels.get(current_state, f"state_{current_state}"),
            "confidence": float(current_proba[current_state]),
            "all_probabilities": {
                self.labels.get(i, f"state_{i}"): float(p)
                for i, p in enumerate(current_proba)
            },
        }

    def _extract_features(self, df: pd.DataFrame) -> np.ndarray:
        """Extract features for HMM input."""
        cols = []

        if "returns" in df.columns:
            cols.append(df["returns"].fillna(0).values)
        else:
            cols.append(df["close"].pct_change().fillna(0).values)

        if "volatility_20" in df.columns:
            cols.append(df["volatility_20"].fillna(0).values)
        else:
            ret = df["close"].pct_change().fillna(0)
            cols.append(ret.rolling(20, min_periods=1).std().fillna(0).values)

        return np.column_stack(cols)


# ==================================================================
# GMM Regime Detector
# ==================================================================

class GMMRegimeDetector:
    """Gaussian Mixture Model for return distribution clustering."""

    def __init__(self, n_components: int = 3, random_state: int = 42):
        self.n_components = n_components
        self.random_state = random_state
        self.model = None
        self.labels = {}

    def fit(self, df: pd.DataFrame) -> "GMMRegimeDetector":
        features = self._extract_features(df)

        self.model = GaussianMixture(
            n_components=self.n_components,
            covariance_type="full",
            random_state=self.random_state,
            n_init=5,
        )
        self.model.fit(features)

        self.labels = _label_regimes(
            self.model.means_,
            np.array([c[0, 0] for c in self.model.covariances_]),
            self.n_components,
        )

        logger.info(f"GMM fitted — {self.n_components} components, labels: {self.labels}")
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("GMM not fitted — call .fit() first")
        return self.model.predict(self._extract_features(df))

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("GMM not fitted — call .fit() first")
        return self.model.predict_proba(self._extract_features(df))

    def get_current_regime(self, df: pd.DataFrame) -> Dict:
        states = self.predict(df)
        probas = self.predict_proba(df)
        current = int(states[-1])
        return {
            "regime_id": current,
            "regime_label": self.labels.get(current, f"cluster_{current}"),
            "confidence": float(probas[-1][current]),
        }

    def _extract_features(self, df: pd.DataFrame) -> np.ndarray:
        cols = []
        if "returns" in df.columns:
            cols.append(df["returns"].fillna(0).values)
        else:
            cols.append(df["close"].pct_change().fillna(0).values)

        if "volatility_20" in df.columns:
            cols.append(df["volatility_20"].fillna(0).values)

        return np.column_stack(cols) if len(cols) > 1 else cols[0].reshape(-1, 1)
