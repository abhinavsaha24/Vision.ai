"""
Sentiment engine — orchestrates news fetching and NLP analysis.
Produces rolling sentiment features for signal fusion.
"""

from __future__ import annotations

import logging
import time
from typing import Dict

import numpy as np

from backend.src.sentiment.news_fetcher import NewsFetcher
from backend.src.sentiment.sentiment_model import SentimentModel

logger = logging.getLogger(__name__)


class SentimentEngine:
    """
    Fetches news, runs NLP sentiment, and maintains rolling sentiment history.
    """

    def __init__(self, history_size: int = 50):
        self.fetcher = NewsFetcher()
        self.model = SentimentModel()

        self.history_size = history_size
        self._score_history = []
        self._last_result = None
        self._last_update = 0
        self._update_interval = 120  # seconds

    def get_sentiment(self) -> Dict:
        """Get current aggregated sentiment."""

        # Rate limit updates
        if (
            self._last_result
            and (time.time() - self._last_update) < self._update_interval
        ):
            return self._last_result

        headlines = self.fetcher.fetch_news()
        result = self.model.analyze(headlines)

        # Track history
        score = result.get("score", 0.0)
        self._score_history.append(score)
        if len(self._score_history) > self.history_size:
            self._score_history = self._score_history[-self.history_size :]

        # Add rolling stats
        scores = np.array(self._score_history)
        result["rolling_mean"] = round(float(np.mean(scores)), 4)
        result["rolling_std"] = (
            round(float(np.std(scores)), 4) if len(scores) > 1 else 0.0
        )
        result["momentum"] = (
            round(float(scores[-1] - scores[0]), 4) if len(scores) > 1 else 0.0
        )
        result["history_length"] = len(self._score_history)

        self._last_result = result
        self._last_update = time.time()

        return result

    def get_sentiment_score(self) -> float:
        """Get just the numeric sentiment score."""
        result = self.get_sentiment()
        return result.get("score", 0.0)

    def get_sentiment_features(self) -> Dict[str, float]:
        """Get sentiment features suitable for ML pipeline."""
        result = self.get_sentiment()
        return {
            "sentiment_score": result.get("score", 0.0),
            "sentiment_rolling_mean": result.get("rolling_mean", 0.0),
            "sentiment_rolling_std": result.get("rolling_std", 0.0),
            "sentiment_momentum": result.get("momentum", 0.0),
        }
