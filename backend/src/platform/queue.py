from __future__ import annotations

import json
import logging
from typing import Any, Iterable, cast

from redis import Redis

logger = logging.getLogger(__name__)


class RedisStreamQueue:
    def __init__(self, redis_url: str):
        self.client = Redis.from_url(redis_url, decode_responses=True)

    def publish(self, stream: str, payload: dict[str, Any]) -> str:
        return cast(
            str,
            self.client.xadd(
                stream,
                {"data": json.dumps(payload)},
                maxlen=50000,
                approximate=True,
            ),
        )

    def ensure_group(self, stream: str, group: str) -> None:
        try:
            self.client.xgroup_create(name=stream, groupname=group, id="0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def consume_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 5000,
        stale_idle_ms: int = 60000,
    ) -> list[tuple[str, dict[str, Any]]]:
        result = cast(
            list[tuple[str, list[tuple[str, dict[str, str]]]]],
            self.client.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams={stream: ">"},
                count=count,
                block=block_ms,
            ),
        )

        records: list[tuple[str, dict[str, Any]]] = []
        if result is not None:
            for _, entries in result:
                for message_id, fields in entries:
                    raw = fields.get("data")
                    if raw is None:
                        logger.warning("queue_message_missing_data message_id=%s fields=%s", message_id, fields)
                        continue
                    try:
                        records.append((message_id, json.loads(raw)))
                    except json.JSONDecodeError:
                        logger.error("queue_message_json_decode_failed message_id=%s raw=%s", message_id, raw)
                        continue

        if records:
            return records

        claimed = self._claim_stale_pending(
            stream=stream,
            group=group,
            consumer=consumer,
            min_idle_ms=max(1000, int(stale_idle_ms)),
            count=count,
        )
        return claimed

    def _claim_stale_pending(
        self,
        stream: str,
        group: str,
        consumer: str,
        min_idle_ms: int,
        count: int,
    ) -> list[tuple[str, dict[str, Any]]]:
        try:
            result = self.client.xautoclaim(
                name=stream,
                groupname=group,
                consumername=consumer,
                min_idle_time=min_idle_ms,
                start_id="0-0",
                count=count,
            )
            if isinstance(result, tuple) and len(result) >= 2:
                claimed = result[1]
            else:
                claimed = []
        except Exception as exc:
            logger.warning("queue_claim_stale_failed stream=%s group=%s err=%s", stream, group, exc)
            return []

        records: list[tuple[str, dict[str, Any]]] = []
        for message_id, fields in claimed:
            raw = fields.get("data")
            if raw is None:
                logger.warning("queue_claimed_message_missing_data message_id=%s fields=%s", message_id, fields)
                continue
            try:
                records.append((message_id, json.loads(raw)))
            except json.JSONDecodeError:
                logger.error("queue_claimed_message_json_decode_failed message_id=%s raw=%s", message_id, raw)
                continue
        return records

    def ack(self, stream: str, group: str, ids: Iterable[str]) -> None:
        ids_list = list(ids)
        if not ids_list:
            return
        self.client.xack(stream, group, *ids_list)

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass

    def readiness_probe(self) -> bool:
        try:
            if not self.client.ping():
                return False
            probe_id = cast(
                str,
                self.client.xadd(
                    "events.healthcheck",
                    {"data": json.dumps({"probe": "ready"})},
                    maxlen=500,
                    approximate=True,
                ),
            )
            rows = self.client.xrange("events.healthcheck", min=probe_id, max=probe_id, count=1)
            return bool(rows)
        except Exception as exc:
            logger.warning("queue_readiness_probe_failed err=%s", exc)
            return False
