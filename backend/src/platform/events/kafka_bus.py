from __future__ import annotations

import json
from typing import Any, Iterable

try:
    from kafka import KafkaConsumer, KafkaProducer, TopicPartition
except Exception:  # pragma: no cover - optional dependency at runtime
    KafkaConsumer = None
    KafkaProducer = None
    TopicPartition = None

from backend.src.platform.events.bus import EventBus


class KafkaEventBus(EventBus):
    def __init__(
        self,
        bootstrap_servers: str,
        client_id: str = "vision-ai",
    ):
        if KafkaProducer is None or KafkaConsumer is None:
            raise RuntimeError(
                "kafka-python package is required for KafkaEventBus."
            )

        self._bootstrap_servers = bootstrap_servers
        self._client_id = client_id
        self._producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers,
            client_id=client_id,
            acks="all",
            retries=5,
            enable_idempotence=True,
            value_serializer=lambda x: json.dumps(x).encode("utf-8"),
            key_serializer=lambda x: x.encode("utf-8") if isinstance(x, str) else None,
        )
        self._consumers: dict[tuple[str, str, str], KafkaConsumer] = {}

    def _consumer(self, topic: str, group: str, consumer_name: str) -> KafkaConsumer:
        key = (topic, group, consumer_name)
        if key not in self._consumers:
            self._consumers[key] = KafkaConsumer(
                topic,
                bootstrap_servers=self._bootstrap_servers,
                group_id=group,
                client_id=f"{self._client_id}-{consumer_name}",
                enable_auto_commit=False,
                auto_offset_reset="latest",
                value_deserializer=lambda x: json.loads(x.decode("utf-8")),
            )
        return self._consumers[key]

    def publish(self, topic: str, payload: dict[str, Any], key: str | None = None) -> str:
        meta = self._producer.send(topic, value=payload, key=key).get(timeout=10)
        return f"{meta.topic}:{meta.partition}:{meta.offset}"

    def consume_group(
        self,
        topic: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 5000,
    ) -> list[tuple[str, dict[str, Any]]]:
        client = self._consumer(topic, group, consumer)
        polled = client.poll(timeout_ms=block_ms, max_records=count)
        records: list[tuple[str, dict[str, Any]]] = []
        for _partition, items in polled.items():
            for msg in items:
                msg_id = f"{msg.topic}:{msg.partition}:{msg.offset}"
                records.append((msg_id, msg.value))
        return records

    def ack(self, topic: str, group: str, ids: Iterable[str]) -> None:
        # Kafka commits offsets per partition/group; commit latest consumed offsets.
        # IDs are accepted for interface parity and audit trails.
        _ = list(ids)
        for (t, g, _c), consumer in self._consumers.items():
            if t == topic and g == group:
                consumer.commit()

    def ensure_group(self, topic: str, group: str) -> None:
        # Group creation is implicit in Kafka when consumer joins.
        _ = (topic, group)

    def readiness_probe(self) -> bool:
        try:
            self._producer.bootstrap_connected()
            return True
        except Exception:
            return False

    def close(self) -> None:
        for consumer in self._consumers.values():
            consumer.close(autocommit=False)
        self._producer.flush(timeout=5)
        self._producer.close(timeout=5)
