from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable


class EventBus(ABC):
    @abstractmethod
    def publish(self, topic: str, payload: dict[str, Any], key: str | None = None) -> str:
        raise NotImplementedError

    @abstractmethod
    def consume_group(
        self,
        topic: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 5000,
    ) -> list[tuple[str, dict[str, Any]]]:
        raise NotImplementedError

    @abstractmethod
    def ack(self, topic: str, group: str, ids: Iterable[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def ensure_group(self, topic: str, group: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def readiness_probe(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError
