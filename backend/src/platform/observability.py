from __future__ import annotations

import time
from typing import Any, cast

from backend.src.platform.queue import RedisStreamQueue


METRICS_HASH_KEY = "vision:metrics:totals"
METRICS_MINUTE_PREFIX = "vision:metrics:minute"


def _metric_total_field(metric: str) -> str:
    return f"{metric}.total"


def _metric_error_field(metric: str) -> str:
    return f"{metric}.errors"


def increment_metric(queue: RedisStreamQueue, metric: str, value: float = 1.0) -> None:
    try:
        client = cast(Any, queue.client)
        client.hincrbyfloat(METRICS_HASH_KEY, _metric_total_field(metric), float(value))
        minute_bucket = int(time.time() // 60)
        minute_key = f"{METRICS_MINUTE_PREFIX}:{metric}:{minute_bucket}"
        pipe = client.pipeline()
        pipe.incrbyfloat(minute_key, float(value))
        pipe.expire(minute_key, 60 * 180)
        pipe.execute()
    except Exception:
        return


def increment_error(queue: RedisStreamQueue, metric: str, value: float = 1.0) -> None:
    try:
        client = cast(Any, queue.client)
        client.hincrbyfloat(METRICS_HASH_KEY, _metric_error_field(metric), float(value))
        client.hincrbyfloat(METRICS_HASH_KEY, "errors.total", float(value))
    except Exception:
        return


def read_totals(queue: RedisStreamQueue) -> dict[str, float]:
    try:
        client = cast(Any, queue.client)
        raw = dict(client.hgetall(METRICS_HASH_KEY))
    except Exception:
        return {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        try:
            out[str(k)] = float(v)
        except Exception:
            out[str(k)] = 0.0
    return out


def trades_per_minute(queue: RedisStreamQueue, lookback_minutes: int = 5) -> float:
    lookback = max(1, int(lookback_minutes))
    now_minute = int(time.time() // 60)
    values: list[float] = []
    for minute_bucket in range(now_minute - lookback + 1, now_minute + 1):
        key = f"{METRICS_MINUTE_PREFIX}:trades_executed:{minute_bucket}"
        try:
            client = cast(Any, queue.client)
            raw = client.get(key)
        except Exception:
            values.append(0.0)
            continue
        if raw is None:
            values.append(0.0)
            continue
        try:
            values.append(float(str(raw)))
        except Exception:
            values.append(0.0)
    return float(sum(values) / max(1, len(values)))


def metrics_snapshot(queue: RedisStreamQueue) -> dict[str, Any]:
    totals = read_totals(queue)
    return {
        "totals": totals,
        "trades_per_minute": trades_per_minute(queue, lookback_minutes=5),
    }
