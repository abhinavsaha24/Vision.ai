from __future__ import annotations

from typing import Any, Iterable

from backend.src.platform.event_bus.bus import EventBus
from backend.src.platform.queue import RedisStreamQueue


class RedisEventBus(EventBus):
    def __init__(self, redis_url: str):
        self._queue = RedisStreamQueue(redis_url)
        self.client = self._queue.client

    def publish(self, topic: str, payload: dict[str, Any], key: str | None = None) -> str:
        if key:
            payload = {**payload, "_event_key": key}
        return self._queue.publish(topic, payload)

    def consume_group(
        self,
        topic: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 5000,
    ) -> list[tuple[str, dict[str, Any]]]:
        return self._queue.consume_group(
            stream=topic,
            group=group,
            consumer=consumer,
            count=count,
            block_ms=block_ms,
        )

    def ack(self, topic: str, group: str, ids: Iterable[str]) -> None:
        self._queue.ack(stream=topic, group=group, ids=ids)

    def ensure_group(self, topic: str, group: str) -> None:
        self._queue.ensure_group(stream=topic, group=group)

    def readiness_probe(self) -> bool:
        return self._queue.readiness_probe()

    def close(self) -> None:
        self._queue.close()
