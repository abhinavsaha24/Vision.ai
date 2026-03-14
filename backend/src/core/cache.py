"""
Redis cache wrapper with graceful fallback.

When Redis is unavailable, operations silently bypass cache
and log a warning. The application never crashes due to cache issues.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import redis — optional dependency
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.info("redis package not installed — cache disabled")


class RedisCache:
    """
    Simple Redis cache with TTL support and graceful degradation.

    Args:
        url: Redis connection URL (e.g. redis://localhost:6379/0)
        default_ttl: default time-to-live in seconds
        enabled: whether caching is enabled
    """

    def __init__(self, url: str = "redis://localhost:6379/0",
                 default_ttl: int = 30, enabled: bool = True):
        self.default_ttl = default_ttl
        self.enabled = enabled and REDIS_AVAILABLE
        self._client = None

        if self.enabled:
            try:
                self._client = redis.from_url(url, decode_responses=True)
                self._client.ping()
                logger.info(f"Redis cache connected: {url}")
            except Exception as e:
                logger.warning(f"Redis unavailable ({e}) — cache disabled")
                self._client = None
                self.enabled = False

    @property
    def connected(self) -> bool:
        return self._client is not None and self.enabled

    def get(self, key: str) -> Optional[str]:
        """Get value from cache. Returns None on miss or error."""
        if not self.connected:
            return None
        try:
            return self._client.get(key)
        except Exception as e:
            logger.warning(f"Cache get error: {e}")
            return None

    def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        """Set value in cache with TTL. Returns True on success."""
        if not self.connected:
            return False
        try:
            self._client.setex(key, ttl or self.default_ttl, value)
            return True
        except Exception as e:
            logger.warning(f"Cache set error: {e}")
            return False

    def get_json(self, key: str) -> Optional[dict]:
        """Get and deserialize JSON from cache."""
        raw = self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def set_json(self, key: str, data: dict, ttl: Optional[int] = None) -> bool:
        """Serialize dict to JSON and store in cache."""
        try:
            return self.set(key, json.dumps(data, default=str), ttl)
        except (TypeError, ValueError) as e:
            logger.warning(f"Cache JSON serialize error: {e}")
            return False

    def delete(self, key: str) -> bool:
        """Delete a key from cache."""
        if not self.connected:
            return False
        try:
            self._client.delete(key)
            return True
        except Exception as e:
            logger.warning(f"Cache delete error: {e}")
            return False

    def flush(self) -> bool:
        """Flush all cached data."""
        if not self.connected:
            return False
        try:
            self._client.flushdb()
            return True
        except Exception as e:
            logger.warning(f"Cache flush error: {e}")
            return False
