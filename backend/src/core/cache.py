"""
Redis cache layer for Vision-AI with graceful in-memory fallback.

Provides:
  - get / set / get_json / set_json  — key-value caching with TTL
  - publish / subscribe              — Redis Pub/Sub for worker commands
  - Graceful degradation             — in-memory dict when Redis is off

Usage:
    from backend.src.core.cache import cache
    cache.set_json("predictions:BTCUSDT", {...}, ttl=30)
    data = cache.get_json("predictions:BTCUSDT")
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

logger = logging.getLogger("vision-ai")

# Try to import redis — optional dependency
try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.info("redis package not installed — cache will use in-memory store")


# ---------------------------------------------------------------------------
# In-memory fallback store (used when Redis is disabled or unavailable)
# ---------------------------------------------------------------------------


class _MemoryStore:
    """Dict-backed cache with TTL support — zero dependencies."""

    def __init__(self):
        self._store: dict[str, tuple[float, str]] = {}

    def get(self, key: str) -> Optional[str]:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires, value = entry
        if expires and time.time() > expires:
            del self._store[key]
            return None
        return value

    def setex(self, key: str, ttl: int, value: str):
        expires = time.time() + ttl if ttl > 0 else 0
        self._store[key] = (expires, value)

    def set(self, key: str, value: str):
        self._store[key] = (0, value)

    def setnx(self, key: str, value: str, ttl: int = 0) -> bool:
        existing = self.get(key)
        if existing is not None:
            return False
        if ttl and ttl > 0:
            self.setex(key, ttl, value)
        else:
            self.set(key, value)
        return True

    def delete(self, key: str):
        self._store.pop(key, None)

    def flushdb(self):
        self._store.clear()

    def ping(self):
        return True

    def publish(self, channel: str, message: str):
        pass  # no-op in memory mode

    def pubsub(self):
        return None  # no-op in memory mode


# ---------------------------------------------------------------------------
# RedisCache wrapper
# ---------------------------------------------------------------------------


class RedisCache:
    """
    Redis cache with TTL support, JSON helpers, and Pub/Sub.
    Falls back to an in-memory dict when Redis is unavailable.
    """

    def __init__(
        self,
        url: str = "redis://localhost:6379/0",
        default_ttl: int = 30,
        enabled: bool = True,
    ):
        self.default_ttl = default_ttl
        self.enabled = enabled and REDIS_AVAILABLE
        self._client = None

        if self.enabled:
            try:
                self._client = redis.from_url(url, decode_responses=True)
                self._client.ping()
                logger.info("Redis cache connected: %s", url)
            except Exception as e:
                logger.warning("Redis unavailable (%s) — using memory fallback", e)
                self._client = None
                self.enabled = False

        # Fallback to memory store if Redis failed or is disabled
        if self._client is None:
            self._client = _MemoryStore()
            logger.info("Cache: using in-memory store")

    @property
    def connected(self) -> bool:
        return self._client is not None

    # ---- Basic key-value ----

    def get(self, key: str) -> Optional[str]:
        try:
            return self._client.get(key)
        except Exception as e:
            logger.warning("Cache get error: %s", e)
            return None

    def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        try:
            effective_ttl = ttl or self.default_ttl
            self._client.setex(key, effective_ttl, value)
            return True
        except Exception as e:
            logger.warning("Cache set error: %s", e)
            return False

    def set_if_absent(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        """Set key only when absent. Returns True if created, False if key exists."""
        effective_ttl = ttl or self.default_ttl
        try:
            # Redis atomic NX path.
            if self.enabled and REDIS_AVAILABLE:
                created = self._client.set(key, value, ex=effective_ttl, nx=True)
                return bool(created)

            # In-memory fallback path.
            if hasattr(self._client, "setnx"):
                return bool(self._client.setnx(key, value, effective_ttl))

            if self.get(key) is not None:
                return False
            return self.set(key, value, ttl=effective_ttl)
        except Exception as e:
            logger.warning("Cache set_if_absent error: %s", e)
            return False

    # ---- JSON helpers ----

    def get_json(self, key: str) -> Optional[Any]:
        raw = self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def set_json(self, key: str, data: Any, ttl: Optional[int] = None) -> bool:
        try:
            return self.set(key, json.dumps(data, default=str), ttl)
        except (TypeError, ValueError) as e:
            logger.warning("Cache JSON serialize error: %s", e)
            return False

    # ---- Pub/Sub (for worker commands) ----

    def publish(self, channel: str, message: Any) -> bool:
        """Publish a message to a Redis channel."""
        try:
            self._client.publish(channel, json.dumps(message, default=str))
            return True
        except Exception as e:
            logger.warning("Cache publish error: %s", e)
            return False

    def subscribe(self, channel: str):
        """Subscribe to a Redis channel. Returns PubSub object or None."""
        try:
            ps = self._client.pubsub()
            if ps:
                ps.subscribe(channel)
            return ps
        except Exception:
            return None

    # ---- Housekeeping ----

    def delete(self, key: str) -> bool:
        try:
            self._client.delete(key)
            return True
        except Exception as e:
            logger.warning("Cache delete error: %s", e)
            return False

    def flush(self) -> bool:
        try:
            self._client.flushdb()
            return True
        except Exception as e:
            logger.warning("Cache flush error: %s", e)
            return False
