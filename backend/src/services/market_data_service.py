"""Market data service: publishes normalized market bar and orderbook events."""

from __future__ import annotations

from fastapi import Request
from pydantic import BaseModel

from backend.src.contracts.events import EventEnvelope, EventName
from backend.src.core.config import settings
from backend.src.core.event_stream import RedisStreamsBus
from backend.src.services.shared.app_factory import create_service_app

app = create_service_app("market-data-service")
bus = RedisStreamsBus(url=settings.redis_url, enabled=settings.redis_enabled)


class BarEvent(BaseModel):
    symbol: str
    timeframe: str = "1m"
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: str


@app.post("/ingest/bar")
async def ingest_bar(payload: BarEvent, request: Request):
    event = EventEnvelope(
        source="market-data-service",
        event_name=EventName.MARKET_BAR_CLOSED,
        correlation_id=getattr(request.state, "correlation_id", None),
        payload=payload.model_dump(),
    )
    stream_id = bus.publish("market.bar.closed", event)
    return {
        "stream": "market.bar.closed",
        "stream_id": stream_id,
        "event_id": event.event_id,
    }
