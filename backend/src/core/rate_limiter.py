"""
In-memory rate limiter middleware for FastAPI.

Uses a sliding window approach per IP + path.
Falls back gracefully — never crashes the server.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Dict, Tuple

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """
    Sliding window rate limiter.

    Args:
        max_requests: max requests per window
        window_seconds: window duration in seconds
        exclude_paths: paths to exclude from rate limiting (e.g. /health)
    """

    def __init__(
        self,
        app,
        max_requests: int = 60,
        window_seconds: int = 60,
        exclude_paths: tuple = (
            "/health",
            "/health/detailed",
            "/",
            "/docs",
            "/openapi.json",
        ),
    ):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.exclude_paths = exclude_paths

        # {(ip, path_prefix): [timestamps]}
        self._requests: Dict[Tuple[str, str], list] = defaultdict(list)
        self._cleanup_counter = 0

    async def dispatch(self, request: Request, call_next):
        try:
            path = request.url.path

            # Skip excluded paths and preflight OPTIONS requests
            if request.method == "OPTIONS" or any(
                path.startswith(ep) for ep in self.exclude_paths
            ):
                return await call_next(request)

            # Get client IP
            client_ip = request.client.host if request.client else "unknown"

            # Use path prefix (first segment) for grouping
            path_prefix = (
                "/" + path.strip("/").split("/")[0] if path.strip("/") else "/"
            )
            key = (client_ip, path_prefix)

            now = time.time()
            window_start = now - self.window_seconds

            # Clean old entries for this key
            self._requests[key] = [t for t in self._requests[key] if t > window_start]

            if len(self._requests[key]) >= self.max_requests:
                retry_after = (
                    int(self._requests[key][0] + self.window_seconds - now) + 1
                )
                logger.warning("Rate limit exceeded for {client_ip} on %s", path_prefix)
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "Rate limit exceeded",
                        "retry_after": retry_after,
                    },
                    headers={"Retry-After": str(retry_after)},
                )

            self._requests[key].append(now)

            # Periodic cleanup of stale keys (every 100 requests)
            self._cleanup_counter += 1
            if self._cleanup_counter >= 100:
                self._cleanup_counter = 0
                self._cleanup_stale_keys()

            return await call_next(request)

        except Exception as e:
            # Never crash the server due to rate limiting
            logger.error("Rate limiter error: %s", e)
            return await call_next(request)

    def _cleanup_stale_keys(self):
        """Remove keys with no recent activity."""
        now = time.time()
        cutoff = now - self.window_seconds * 2
        stale = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._requests[k]
