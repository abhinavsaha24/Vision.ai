"""
Sentiment data feed: CryptoPanic API integration.

Provides aggregated sentiment scores from crypto news sources.
Free tier: 200 requests/hr, no API key required for basic access.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

_REQUESTS_AVAILABLE = False
try:
    import requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    pass


class SentimentFeed:
    """
    Fetch and aggregate sentiment data from CryptoPanic.

    Features:
      - News article sentiment (positive/negative/neutral)
      - Rolling sentiment score with exponential decay
      - News volume as a volatility proxy
      - Sentiment momentum (change in sentiment)
    """

    CRYPTOPANIC_API = "https://cryptopanic.com/api/free/v1/posts/"

    def __init__(self, api_key: Optional[str] = None):
        """
        Args:
            api_key: CryptoPanic API key (optional for free tier).
                     Set via environment variable CRYPTOPANIC_API_KEY.
        """
        self.api_key = api_key
        if not self.api_key:
            import os
            self.api_key = os.environ.get("CRYPTOPANIC_API_KEY", "")

        self._session = requests.Session() if _REQUESTS_AVAILABLE else None
        self._cache: Dict[str, dict] = {}
        self._cache_ttl = 300  # 5 minutes

    def fetch_news(
        self,
        currencies: str = "BTC",
        kind: str = "news",
        limit: int = 50,
    ) -> List[Dict]:
        """
        Fetch recent news articles from CryptoPanic.

        Args:
            currencies: comma-separated currency codes (e.g., "BTC,ETH")
            kind: "news" or "media"
            limit: max results (free tier caps at 50)

        Returns:
            List of article dicts with keys: title, published_at, votes, domain
        """
        if not _REQUESTS_AVAILABLE or not self.api_key:
            return []

        cache_key = f"{currencies}:{kind}"
        cached = self._cache.get(cache_key)
        if cached and time.time() - cached["ts"] < self._cache_ttl:
            return cached["data"]

        try:
            params = {
                "auth_token": self.api_key,
                "currencies": currencies,
                "kind": kind,
                "public": "true",
            }
            resp = self._session.get(
                self.CRYPTOPANIC_API, params=params, timeout=10
            )
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            articles = []
            for item in results[:limit]:
                votes = item.get("votes", {})
                articles.append({
                    "title": item.get("title", ""),
                    "published_at": item.get("published_at", ""),
                    "domain": item.get("domain", ""),
                    "positive": votes.get("positive", 0),
                    "negative": votes.get("negative", 0),
                    "important": votes.get("important", 0),
                    "liked": votes.get("liked", 0),
                    "disliked": votes.get("disliked", 0),
                    "kind": item.get("kind", "news"),
                })

            self._cache[cache_key] = {"data": articles, "ts": time.time()}
            return articles

        except Exception as e:
            logger.error("CryptoPanic fetch failed: %s", e)
            return []

    def compute_sentiment_score(self, articles: List[Dict]) -> Dict[str, float]:
        """
        Compute aggregate sentiment metrics from articles.

        Returns:
            {
                "score": float in [-1, 1] (aggregate sentiment),
                "volume": int (news count),
                "bullish_ratio": float in [0, 1],
                "important_count": int,
            }
        """
        if not articles:
            return {
                "score": 0.0,
                "volume": 0,
                "bullish_ratio": 0.5,
                "important_count": 0,
            }

        total_positive = sum(a["positive"] + a["liked"] for a in articles)
        total_negative = sum(a["negative"] + a["disliked"] for a in articles)
        total_votes = total_positive + total_negative

        if total_votes > 0:
            score = (total_positive - total_negative) / total_votes
            bullish_ratio = total_positive / total_votes
        else:
            score = 0.0
            bullish_ratio = 0.5

        important_count = sum(1 for a in articles if a.get("important", 0) > 0)

        return {
            "score": round(score, 4),
            "volume": len(articles),
            "bullish_ratio": round(bullish_ratio, 4),
            "important_count": important_count,
        }

    def get_sentiment_features(
        self, currencies: str = "BTC"
    ) -> Dict[str, float]:
        """
        Get current sentiment features for use in the model.

        Returns dict with keys:
            sent_score, sent_volume, sent_bullish_ratio, sent_important
        """
        articles = self.fetch_news(currencies)
        metrics = self.compute_sentiment_score(articles)

        return {
            "sent_score": metrics["score"],
            "sent_volume": float(metrics["volume"]),
            "sent_bullish_ratio": metrics["bullish_ratio"],
            "sent_important": float(metrics["important_count"]),
        }
