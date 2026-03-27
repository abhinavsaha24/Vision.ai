from __future__ import annotations

import logging

from backend.src.platform.config import settings
from backend.src.platform.event_bus.bus import EventBus
from backend.src.platform.event_bus.kafka_bus import KafkaEventBus
from backend.src.platform.event_bus.redis_bus import RedisEventBus

logger = logging.getLogger(__name__)


def create_event_bus() -> EventBus:
    backend = str(settings.event_bus_backend).strip().lower()
    if backend == "kafka":
        try:
            logger.info("event_bus_backend_selected backend=kafka servers=%s", settings.kafka_bootstrap_servers)
            return KafkaEventBus(
                bootstrap_servers=settings.kafka_bootstrap_servers,
                client_id=settings.service_name,
            )
        except Exception as exc:
            logger.warning("event_bus_kafka_init_failed err=%s fallback=redis", exc)

    logger.info("event_bus_backend_selected backend=redis url=%s", settings.redis_url)
    return RedisEventBus(settings.redis_url)
