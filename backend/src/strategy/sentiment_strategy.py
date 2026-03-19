"""
Sentiment-based trading strategy — research-backed implementation.

Based on: RavenPack/FinBERT news sentiment analysis research

Aggregated sentiment factor:
  S_t = Σ(s_{t-k} · w_k) / Σ(w_k)
  where w_k = exp(-k/τ) are time-decay weights

Features:
  - Time-decayed sentiment aggregation
  - Novelty weighting (newer news counts more)
  - Composite scoring from level + momentum
  - Configurable thresholds for LONG/SHORT/FLAT
"""

from __future__ import annotations

import logging
from typing import Dict

import numpy as np

logger = logging.getLogger(__name__)


class SentimentStrategy:
    """
    Sentiment-driven trading signals using time-decayed aggregation.

    Aggregates sentiment scores over a window with exponential time-decay,
    then combines level and momentum for a composite signal.

    Parameters:
        bullish_threshold: sentiment above this → long
        bearish_threshold: sentiment below this → short
        decay_tau: time-decay factor (higher = slower decay)
        momentum_weight: weight of sentiment momentum vs level
        min_news_count: minimum news items required for a signal
    """

    def __init__(
        self,
        bullish_threshold: float = 0.3,
        bearish_threshold: float = -0.3,
        decay_tau: float = 3.0,
        momentum_weight: float = 0.3,
        min_news_count: int = 2,
    ):
        self.bullish_threshold = bullish_threshold
        self.bearish_threshold = bearish_threshold
        self.decay_tau = decay_tau
        self.momentum_weight = momentum_weight
        self.min_news_count = min_news_count

    def generate_signal(self, sentiment_data: dict = None, **kwargs) -> int:
        """
        Generate trading signal from sentiment data.

        Args:
            sentiment_data: dict with keys:
                - 'score': current sentiment score (-1 to +1)
                - 'rolling_mean': rolling average sentiment
                - 'momentum': change in sentiment over window
                - 'news_count': number of recent news items
                - 'scores': list of individual scores (optional)
                - 'ages': list of ages in days (optional, for decay)

        Returns:
            1 (long), -1 (short), or 0 (flat)
        """
        if sentiment_data is None:
            return 0

        try:
            # If raw scores and ages provided, compute time-decayed aggregate
            scores = sentiment_data.get("scores")
            ages = sentiment_data.get("ages")

            if scores and ages and len(scores) >= self.min_news_count:
                composite = self._time_decayed_aggregate(scores, ages)
            else:
                # Use pre-computed values
                score = sentiment_data.get("score", 0.0)
                rolling_mean = sentiment_data.get("rolling_mean", score)
                momentum = sentiment_data.get("momentum", 0.0)
                news_count = sentiment_data.get("news_count", 0)

                if news_count < self.min_news_count:
                    return 0

                # Composite: level + momentum
                level_weight = 1 - self.momentum_weight
                composite = level_weight * score + self.momentum_weight * momentum

                # Stabilize with rolling mean
                composite = 0.7 * composite + 0.3 * rolling_mean

            # Signal generation
            if composite > self.bullish_threshold:
                return 1
            elif composite < self.bearish_threshold:
                return -1
            return 0

        except Exception as e:
            logger.error("SentimentStrategy error: %s", e)
            return 0

    def _time_decayed_aggregate(self, scores: list, ages: list) -> float:
        """
        Compute time-decayed weighted average of sentiment scores.

        S_t = Σ(s_k · w_k) / Σ(w_k)
        where w_k = exp(-age_k / τ)
        """
        try:
            scores_arr = np.array(scores, dtype=float)
            ages_arr = np.array(ages, dtype=float)

            # Exponential time-decay weights
            weights = np.exp(-ages_arr / self.decay_tau)

            # Weighted average
            total_weight = np.sum(weights)
            if total_weight <= 0:
                return 0.0

            return float(np.sum(scores_arr * weights) / total_weight)

        except Exception:
            return 0.0

    def compute_sentiment_features(self, sentiment_data: dict) -> Dict:
        """
        Compute detailed sentiment features for downstream use.

        Returns dict with level, momentum, decay-weighted score, and strength.
        """
        if not sentiment_data:
            return {"sentiment_composite": 0.0, "sentiment_strength": 0.0}

        score = sentiment_data.get("score", 0.0)
        rolling_mean = sentiment_data.get("rolling_mean", 0.0)
        momentum = sentiment_data.get("momentum", 0.0)

        composite = (1 - self.momentum_weight) * score + self.momentum_weight * momentum
        composite = 0.7 * composite + 0.3 * rolling_mean

        return {
            "sentiment_composite": round(composite, 4),
            "sentiment_level": round(score, 4),
            "sentiment_momentum": round(momentum, 4),
            "sentiment_strength": round(abs(composite), 4),
            "sentiment_direction": (
                "bullish"
                if composite > 0
                else "bearish" if composite < 0 else "neutral"
            ),
        }
