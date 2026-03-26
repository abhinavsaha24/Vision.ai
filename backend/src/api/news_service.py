"""
News aggregation service - fetches from multiple APIs server-side.

Sources:
  - CryptoPanic  (crypto news)
  - Finnhub      (market news)
  - NewsAPI      (global headlines)
  - CoinGecko    (trending coins - free, no key)

Each article normalized to:
  { title, url, source, timestamp, sentiment, importance }

Caching:
  Results cached for 5 minutes to avoid rate limits.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests

from backend.src.core.config import settings

logger = logging.getLogger(__name__)

CACHE_TTL = 300  # 5 minutes


@dataclass
class NewsArticle:
    title: str
    url: str
    source: str
    timestamp: str
    sentiment: Optional[float] = None
    importance: Optional[float] = None


class NewsAggregator:
    """Multi-source news aggregation with caching and deduplication."""

    def __init__(self):
        self.cryptopanic_token = (
            os.getenv("CRYPTOPANIC_TOKEN") or settings.cryptopanic_token
        )
        self.newsapi_key = os.getenv("NEWSAPI_KEY") or settings.newsapi_key
        self.finnhub_key = os.getenv("FINNHUB_KEY") or settings.finnhub_key

        if not self.cryptopanic_token:
            raise RuntimeError("CRYPTOPANIC_TOKEN environment variable must be set")
        if not self.newsapi_key:
            raise RuntimeError("NEWSAPI_KEY environment variable must be set")
        if not self.finnhub_key:
            raise RuntimeError("FINNHUB_KEY environment variable must be set")

        # Cache
        self._cache: List[Dict] = []
        self._cache_time: float = 0

    def get_news(self, limit: int = 30) -> List[Dict]:
        """Get aggregated news from all sources (cached)."""

        if self._cache and (time.time() - self._cache_time < CACHE_TTL):
            return self._cache[:limit]

        articles: List[NewsArticle] = []

        # Fetch from all sources
        articles.extend(self._fetch_cryptopanic())
        articles.extend(self._fetch_finnhub())
        articles.extend(self._fetch_newsapi())
        articles.extend(self._fetch_coingecko_trending())

        # Deduplicate by title hash
        seen = set()
        unique = []
        for a in articles:
            key = hashlib.md5(a.title.lower().strip().encode()).hexdigest()
            if key not in seen:
                seen.add(key)
                unique.append(a)

        # Sort by timestamp (newest first)
        unique.sort(key=lambda a: a.timestamp or "", reverse=True)

        self._cache = [asdict(a) for a in unique]
        self._cache_time = time.time()

        logger.info("News aggregated: {len(self._cache)} articles from %s unique", len(seen))

        return self._cache[:limit]

    # --------------------------------------------------
    # CryptoPanic
    # --------------------------------------------------

    def _fetch_cryptopanic(self) -> List[NewsArticle]:
        """Fetch crypto news from CryptoPanic API."""
        if not self.cryptopanic_token:
            return []

        try:
            url = (
                f"https://cryptopanic.com/api/developer/v2/posts/"
                f"?auth_token={self.cryptopanic_token}"
                f"&currencies=BTC,ETH,SOL"
                f"&public=true"
            )

            res = requests.get(url, timeout=10)

            if res.status_code != 200:
                logger.warning("CryptoPanic returned %s", res.status_code)
                return []

            data = res.json()
            results = data.get("results", [])

            articles = []
            for item in results[:15]:
                # CryptoPanic provides sentiment votes
                votes = item.get("votes", {})
                positive = votes.get("positive", 0)
                negative = votes.get("negative", 0)
                total = positive + negative
                sentiment = (positive - negative) / total if total > 0 else 0.0

                articles.append(
                    NewsArticle(
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        source="CryptoPanic",
                        timestamp=item.get("published_at", ""),
                        sentiment=round(sentiment, 3),
                        importance=item.get("importance", 0),
                    )
                )

            logger.info("CryptoPanic: %s articles", len(articles))
            return articles

        except Exception as e:
            logger.error("CryptoPanic error: %s", e)
            return []

    # --------------------------------------------------
    # Finnhub
    # --------------------------------------------------

    def _fetch_finnhub(self) -> List[NewsArticle]:
        """Fetch market news from Finnhub API."""
        if not self.finnhub_key:
            return []

        try:
            url = (
                f"https://finnhub.io/api/v1/news"
                f"?category=crypto"
                f"&token={self.finnhub_key}"
            )

            res = requests.get(url, timeout=10)

            if res.status_code != 200:
                logger.warning("Finnhub returned %s", res.status_code)
                return []

            data = res.json()

            articles = []
            for item in data[:15]:
                articles.append(
                    NewsArticle(
                        title=item.get("headline", ""),
                        url=item.get("url", ""),
                        source="Finnhub",
                        timestamp=(
                            datetime.fromtimestamp(item.get("datetime", 0)).isoformat()
                            if item.get("datetime")
                            else ""
                        ),
                        sentiment=None,
                        importance=None,
                    )
                )

            logger.info("Finnhub: %s articles", len(articles))
            return articles

        except Exception as e:
            logger.error("Finnhub error: %s", e)
            return []

    # --------------------------------------------------
    # NewsAPI
    # --------------------------------------------------

    def _fetch_newsapi(self) -> List[NewsArticle]:
        """Fetch financial headlines from NewsAPI."""
        if not self.newsapi_key:
            return []

        try:
            url = (
                f"https://newsapi.org/v2/everything"
                f"?q=bitcoin OR ethereum OR crypto"
                f"&sortBy=publishedAt"
                f"&pageSize=15"
                f"&apiKey={self.newsapi_key}"
            )

            res = requests.get(url, timeout=10)

            if res.status_code != 200:
                logger.warning("NewsAPI returned %s", res.status_code)
                return []

            data = res.json()

            articles = []
            for item in data.get("articles", [])[:15]:
                articles.append(
                    NewsArticle(
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        source=item.get("source", {}).get("name", "NewsAPI"),
                        timestamp=item.get("publishedAt", ""),
                        sentiment=None,
                        importance=None,
                    )
                )

            logger.info("NewsAPI: %s articles", len(articles))
            return articles

        except Exception as e:
            logger.error("NewsAPI error: %s", e)
            return []

    # --------------------------------------------------
    # CoinGecko (free, no API key required)
    # --------------------------------------------------

    def _fetch_coingecko_trending(self) -> List[NewsArticle]:
        """Fetch trending coins from CoinGecko as pseudo-news items."""
        try:
            url = "https://api.coingecko.com/api/v3/search/trending"
            res = requests.get(url, timeout=10)

            if res.status_code != 200:
                return []

            data = res.json()
            coins = data.get("coins", [])

            articles = []
            for item in coins[:7]:
                coin = item.get("item", {})
                name = coin.get("name", "")
                symbol = coin.get("symbol", "")
                rank = coin.get("market_cap_rank", "N/A")

                articles.append(
                    NewsArticle(
                        title=f"Trending: {name} ({symbol}) - Market Cap Rank #{rank}",
                        url=f"https://www.coingecko.com/en/coins/{coin.get('id', '')}",
                        source="CoinGecko Trending",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        sentiment=0.3,  # trending = mildly positive
                        importance=0.5,
                    )
                )

            logger.info("CoinGecko: %s trending coins", len(articles))
            return articles

        except Exception as e:
            logger.error("CoinGecko error: %s", e)
            return []
