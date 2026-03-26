"""
Multi-source news fetcher with caching and rate limiting.

Sources:
  - CryptoPanic API
  - NewsAPI
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import List

import requests

from backend.src.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    """Structured news item."""

    title: str
    source: str
    url: str = ""
    published_at: str = ""
    currencies: List[str] = field(default_factory=list)


class NewsFetcher:
    """Multi-source news fetcher with caching."""

    def __init__(self):
        self.cryptopanic_token = (
            os.getenv("CRYPTOPANIC_TOKEN") or settings.cryptopanic_token
        )
        self.newsapi_key = os.getenv("NEWSAPI_KEY") or settings.newsapi_key

        if not self.cryptopanic_token:
            raise RuntimeError("CRYPTOPANIC_TOKEN environment variable must be set")
        if not self.newsapi_key:
            raise RuntimeError("NEWSAPI_KEY environment variable must be set")

        self._cache: List[NewsItem] = []
        self._cache_time: float = 0
        self._cache_ttl: float = 120  # 2 minutes

    # --------------------------------------------------
    # CryptoPanic
    # --------------------------------------------------

    def _fetch_cryptopanic(self, limit: int = 20) -> List[NewsItem]:
        """Fetch from CryptoPanic API."""
        if not self.cryptopanic_token:
            return []

        try:
            url = "https://cryptopanic.com/api/v1/posts/"
            params = {
                "auth_token": self.cryptopanic_token,
                "kind": "news",
                "filter": "important",
            }

            response = requests.get(url, params=params, timeout=10)
            data = response.json()

            items = []
            for item in data.get("results", [])[:limit]:
                currencies = []
                for c in item.get("currencies", []):
                    if isinstance(c, dict):
                        currencies.append(c.get("code", ""))

                items.append(
                    NewsItem(
                        title=item.get("title", ""),
                        source="cryptopanic",
                        url=item.get("url", ""),
                        published_at=item.get("published_at", ""),
                        currencies=currencies,
                    )
                )

            return items

        except Exception as e:
            logger.warning("CryptoPanic fetch failed: %s", e)
            return []

    # --------------------------------------------------
    # NewsAPI
    # --------------------------------------------------

    def _fetch_newsapi(
        self, query: str = "cryptocurrency bitcoin", limit: int = 20
    ) -> List[NewsItem]:
        """Fetch from NewsAPI."""
        if not self.newsapi_key:
            return []

        try:
            url = "https://newsapi.org/v2/everything"
            params = {
                "apiKey": self.newsapi_key,
                "q": query,
                "sortBy": "publishedAt",
                "pageSize": limit,
                "language": "en",
            }

            response = requests.get(url, params=params, timeout=10)
            data = response.json()

            items = []
            for article in data.get("articles", [])[:limit]:
                items.append(
                    NewsItem(
                        title=article.get("title", ""),
                        source="newsapi",
                        url=article.get("url", ""),
                        published_at=article.get("publishedAt", ""),
                    )
                )

            return items

        except Exception as e:
            logger.warning("NewsAPI fetch failed: %s", e)
            return []

    # --------------------------------------------------
    # Public API
    # --------------------------------------------------

    def fetch_news(self, limit: int = 30) -> List[str]:
        """Fetch headlines from all sources. Returns list of title strings."""
        items = self.fetch_news_items(limit)
        return [item.title for item in items if item.title]

    def fetch_news_items(self, limit: int = 30) -> List[NewsItem]:
        """Fetch structured news items from all sources (with cache)."""

        # Check cache
        if self._cache and (time.time() - self._cache_time) < self._cache_ttl:
            return self._cache[:limit]

        items: List[NewsItem] = []

        # CryptoPanic
        crypto_news = self._fetch_cryptopanic(limit=limit)
        items.extend(crypto_news)

        # NewsAPI
        newsapi_news = self._fetch_newsapi(limit=limit)
        items.extend(newsapi_news)

        # Deduplicate by title
        seen = set()
        unique = []
        for item in items:
            key = item.title.lower().strip()
            if key and key not in seen:
                seen.add(key)
                unique.append(item)

        self._cache = unique
        self._cache_time = time.time()

        logger.info("Fetched %s news items", len(unique))
        return unique[:limit]
