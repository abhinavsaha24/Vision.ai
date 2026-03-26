from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from backend.src.platform.config import settings
from backend.src.platform.db import Database
from backend.src.platform.events import EventType, TradingEvent
from backend.src.platform.logging import setup_structured_logging
from backend.src.platform.observability import metrics_snapshot
from backend.src.platform.queue import RedisStreamQueue
from backend.src.platform.repository import (
    ensure_schema,
    get_pipeline_counts,
    get_latest_portfolio,
    is_strategy_enabled,
)

logger = logging.getLogger(__name__)


class StrategyControlRequest(BaseModel):
    strategy_name: str = Field(default="default")


class MarketTickRequest(BaseModel):
    symbol: str = Field(default=settings.default_symbol)
    price: float = Field(gt=0)
    volume: float = Field(default=0, ge=0)
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_startup()
    setup_structured_logging(settings.log_level)
    logger.info("startup_environment_validated diagnostics=%s", settings.startup_diagnostics())
    db = Database(settings.database_url_value)
    queue = RedisStreamQueue(settings.redis_url)

    try:
        ensure_schema(db)
        queue.ensure_group("events.trading", "trading-engine")
        queue.ensure_group("events.trading", "risk-engine")
        queue.ensure_group("events.execution", "execution-engine")
    except Exception:
        queue.close()
        db.close()
        raise

    app.state.db = db
    app.state.queue = queue
    flushed = _flush_outbox(db, queue, max_rows=500)
    if flushed > 0:
        logger.info("outbox_replayed delivered=%s", flushed)
    logger.info("api_service_started")

    yield

    queue.close()
    db.close()
    logger.info("api_service_stopped")


app = FastAPI(
    title="Vision AI Control Plane",
    version="1.0.0",
    description="Stateless API gateway for strategy control and portfolio queries",
    lifespan=lifespan,
)


def _db(request: Request) -> Database:
    return request.app.state.db


def _queue(request: Request) -> RedisStreamQueue:
    return request.app.state.queue


def _set_strategy_and_persist_event(db: Database, strategy_name: str, enabled: bool, event: TradingEvent) -> None:
    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO strategy_control(strategy_name, enabled, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT(strategy_name)
                DO UPDATE SET enabled = EXCLUDED.enabled, updated_at = NOW()
                """,
                (strategy_name, enabled),
            )
            cur.execute(
                """
                INSERT INTO trading_events(event_id, event_type, source, idempotency_key, payload)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                ON CONFLICT(event_id) DO NOTHING
                """,
                (
                    event.event_id,
                    event.event_type.value,
                    event.source,
                    event.idempotency_key,
                    json.dumps(event.payload),
                ),
            )
            cur.execute(
                """
                INSERT INTO event_outbox(event_id, stream, payload)
                VALUES (%s, %s, %s::jsonb)
                ON CONFLICT(event_id)
                DO UPDATE SET stream = EXCLUDED.stream, payload = EXCLUDED.payload
                """,
                (event.event_id, "events.trading", json.dumps(event.to_dict())),
            )


def _persist_event_to_outbox(db: Database, event: TradingEvent, stream: str) -> None:
    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO trading_events(event_id, event_type, source, idempotency_key, payload)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                ON CONFLICT(event_id) DO NOTHING
                """,
                (
                    event.event_id,
                    event.event_type.value,
                    event.source,
                    event.idempotency_key,
                    json.dumps(event.payload),
                ),
            )
            cur.execute(
                """
                INSERT INTO event_outbox(event_id, stream, payload)
                VALUES (%s, %s, %s::jsonb)
                ON CONFLICT(event_id)
                DO UPDATE SET stream = EXCLUDED.stream, payload = EXCLUDED.payload
                """,
                (event.event_id, stream, json.dumps(event.to_dict())),
            )


def _flush_outbox(db: Database, queue: RedisStreamQueue, max_rows: int = 100) -> int:
    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT outbox_id, stream, payload::text
                FROM event_outbox
                ORDER BY outbox_id ASC
                FOR UPDATE SKIP LOCKED
                LIMIT %s
                """,
                (max(1, int(max_rows)),),
            )
            rows = cur.fetchall()

            delivered_ids: list[int] = []
            delivered = 0
            for outbox_id, stream, payload_text in rows:
                try:
                    queue.publish(str(stream), json.loads(payload_text))
                    delivered_ids.append(int(outbox_id))
                    delivered += 1
                except Exception as exc:
                    logger.warning("outbox_publish_failed outbox_id=%s stream=%s err=%s", outbox_id, stream, exc)
                    continue

            if delivered_ids:
                cur.execute(
                    "DELETE FROM event_outbox WHERE outbox_id = ANY(%s)",
                    (delivered_ids,),
                )

    return delivered


def _artifact_path(filename: str) -> Path:
    base = Path(settings.artifacts_dir).resolve()
    candidate = (base / filename).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid_artifact_path:{filename}") from exc
    return candidate


def _read_artifact(filename: str) -> dict:
    path = _artifact_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"artifact_not_found:{filename}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("artifact_read_failed filename=%s err=%s", filename, exc)
        raise HTTPException(status_code=500, detail=f"artifact_read_failed:{filename}") from exc


def _read_artifact_optional(filename: str) -> dict:
    path = _artifact_path(filename)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "api-service"}


@app.get("/health/ready")
def health_ready(request: Request) -> dict[str, str]:
    db = _db(request)
    queue = _queue(request)
    row = db.fetchone("SELECT 1")
    if row is None:
        raise HTTPException(status_code=503, detail="database_not_ready")
    if not queue.readiness_probe():
        raise HTTPException(status_code=503, detail="redis_not_ready")
    return {"status": "ready"}


@app.get("/health/deep")
def health_deep(request: Request) -> dict:
    db = _db(request)
    queue = _queue(request)

    db_ready = db.fetchone("SELECT 1") is not None
    redis_ready = queue.readiness_probe()

    groups_ok = True
    group_details: dict[str, object] = {}
    try:
        group_details["events.trading"] = queue.client.xinfo_groups("events.trading")
        group_details["events.execution"] = queue.client.xinfo_groups("events.execution")
    except Exception as exc:
        groups_ok = False
        group_details["error"] = str(exc)

    counts = get_pipeline_counts(db)
    metrics = metrics_snapshot(queue)

    status = "ready" if (db_ready and redis_ready and groups_ok) else "degraded"
    return {
        "status": status,
        "checks": {
            "database": db_ready,
            "redis": redis_ready,
            "queue_groups": groups_ok,
        },
        "pipeline_counts": counts,
        "metrics": metrics,
        "queue_groups": group_details,
    }


@app.get("/metrics")
def metrics(request: Request) -> dict:
    queue = _queue(request)
    db = _db(request)
    return {
        "metrics": metrics_snapshot(queue),
        "pipeline_counts": get_pipeline_counts(db),
    }


@app.post("/strategy/start")
def start_strategy(payload: StrategyControlRequest, request: Request) -> dict[str, str]:
    db = _db(request)
    queue = _queue(request)

    event = TradingEvent(
        event_type=EventType.STRATEGY_START,
        payload={"strategy_name": payload.strategy_name},
        source="api-service",
        idempotency_key=f"start:{payload.strategy_name}",
    )
    _set_strategy_and_persist_event(db, payload.strategy_name, True, event)
    _flush_outbox(db, queue, max_rows=100)
    return {"status": "queued", "event_id": event.event_id}


@app.post("/strategy/stop")
def stop_strategy(payload: StrategyControlRequest, request: Request) -> dict[str, str]:
    db = _db(request)
    queue = _queue(request)

    event = TradingEvent(
        event_type=EventType.STRATEGY_STOP,
        payload={"strategy_name": payload.strategy_name},
        source="api-service",
        idempotency_key=f"stop:{payload.strategy_name}",
    )
    _set_strategy_and_persist_event(db, payload.strategy_name, False, event)
    _flush_outbox(db, queue, max_rows=100)
    return {"status": "queued", "event_id": event.event_id}


@app.get("/strategy/status/{strategy_name}")
def strategy_status(strategy_name: str, request: Request) -> dict[str, bool | str]:
    enabled = is_strategy_enabled(_db(request), strategy_name)
    return {"strategy_name": strategy_name, "enabled": enabled}


@app.post("/events/market")
def publish_market_tick(payload: MarketTickRequest, request: Request) -> dict[str, str]:
    db = _db(request)
    queue = _queue(request)

    event = TradingEvent(
        event_type=EventType.MARKET_TICK,
        payload=payload.model_dump(),
        source="api-service",
    )
    _persist_event_to_outbox(db, event, "events.trading")
    _flush_outbox(db, queue, max_rows=100)
    return {"status": "accepted", "event_id": event.event_id}


@app.get("/portfolio/latest")
def portfolio_latest(request: Request) -> dict[str, float]:
    return get_latest_portfolio(_db(request))


@app.get("/events/{event_id}")
def event_detail(event_id: str, request: Request) -> dict[str, str | dict]:
    row = _db(request).fetchone(
        """
        SELECT event_type, source, payload::text
        FROM trading_events
        WHERE event_id = %s
        """,
        (event_id,),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="event_not_found")
    payload = json.loads(row[2]) if row[2] else {}
    trace_id = payload.get("trace_id") if isinstance(payload, dict) else None
    out = {
        "event_id": event_id,
        "event_type": row[0],
        "source": row[1],
        "payload": payload,
    }
    if trace_id:
        out["trace_id"] = str(trace_id)
    return out


@app.get("/ops/diagnostics/latest")
def diagnostics_latest() -> dict:
    return _read_artifact("failure_diagnostics.json")


@app.get("/ops/lifecycle/latest")
def lifecycle_latest() -> dict:
    return _read_artifact("edge_lifecycle.json")


@app.get("/ops/allocator/latest")
def allocator_latest() -> dict:
    return _read_artifact("allocator_snapshot.json")


@app.get("/ops/shadow/latest")
def shadow_latest() -> dict:
    return _read_artifact_optional("shadow_performance.json")


@app.get("/ops/flow-ablation/latest")
def flow_ablation_latest() -> dict:
    return _read_artifact_optional("with_without_flow_report.json")


@app.get("/ops/readiness/latest")
def readiness_latest() -> dict:
    return {
        "diagnostics": _read_artifact("failure_diagnostics.json"),
        "lifecycle": _read_artifact("edge_lifecycle.json"),
        "allocator": _read_artifact("allocator_snapshot.json"),
        "shadow": _read_artifact_optional("shadow_performance.json"),
        "flow_ablation": _read_artifact_optional("with_without_flow_report.json"),
    }
