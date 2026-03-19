"""Redis Streams based event bus with idempotent consumption helpers."""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Dict, List

from backend.src.contracts.events import EventEnvelope

logger = logging.getLogger("vision-ai.events.stream")

try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover
    REDIS_AVAILABLE = False


class _MemoryStream:
    def __init__(self):
        self._messages: Dict[str, deque] = {}

    def xadd(
        self,
        stream: str,
        fields: Dict[str, str],
        maxlen: int = 100000,
        approximate: bool = True,
    ):
        q = self._messages.setdefault(stream, deque(maxlen=maxlen))
        msg_id = f"{int(time.time() * 1000)}-0"
        q.append((msg_id, fields))
        return msg_id

    def xread(self, streams: Dict[str, str], count: int = 100, block: int = 0):
        out = []
        for stream in streams:
            q = self._messages.get(stream, deque())
            if not q:
                continue
            out.append((stream, list(q)[-count:]))
        return out


class RedisStreamsBus:
    """Simple bus abstraction for publishing and consuming envelope events."""

    def __init__(self, url: str = "redis://localhost:6379/0", enabled: bool = True):
        self.enabled = bool(enabled and REDIS_AVAILABLE)
        self._client = None
        self._processed: set[str] = set()

        if self.enabled:
            try:
                self._client = redis.from_url(url, decode_responses=True)
                self._client.ping()
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "Redis Streams unavailable (%s), using memory fallback", exc
                )
                self._client = None
                self.enabled = False

        if self._client is None:
            self._client = _MemoryStream()

    def publish(self, stream: str, event: EventEnvelope) -> str:
        payload = event.model_dump_json()
        return self._client.xadd(
            stream, {"event": payload}, maxlen=100000, approximate=True
        )

    def read(
        self, stream: str, last_id: str = "0-0", count: int = 100
    ) -> List[EventEnvelope]:
        rows = self._client.xread({stream: last_id}, count=count, block=0)
        events: List[EventEnvelope] = []
        for _, messages in rows:
            for msg_id, data in messages:
                raw = data.get("event") if isinstance(data, dict) else None
                if not raw:
                    continue
                evt = EventEnvelope.model_validate_json(raw)
                key = f"{stream}:{evt.event_id}:{msg_id}"
                if key in self._processed:
                    continue
                self._processed.add(key)
                events.append(evt)
        if len(self._processed) > 100000:
            self._processed = set(list(self._processed)[-50000:])
        return events
