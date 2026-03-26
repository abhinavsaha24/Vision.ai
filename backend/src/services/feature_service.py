"""Feature service: computes features and emits feature.vector.ready events."""

from __future__ import annotations

from fastapi import Request

from backend.src.contracts.events import EventEnvelope, EventName
from backend.src.core.config import settings
from backend.src.core.event_stream import RedisStreamsBus
from backend.src.data.fetcher import DataFetcher
from backend.src.features.indicators import FeatureEngineer
from backend.src.services.shared.app_factory import create_service_app

app = create_service_app("feature-service")
bus = RedisStreamsBus(url=settings.redis_url, enabled=settings.redis_enabled)
fetcher = DataFetcher()
engineer = FeatureEngineer()


@app.get("/features/compute")
async def compute_features(symbol: str = "BTC/USDT", request: Request = None):
    df = fetcher.fetch(symbol)
    df = engineer.add_all_indicators(df, add_target=False)
    last_row = df.tail(1).to_dict("records")[0] if len(df) else {}
    event = EventEnvelope(
        source="feature-service",
        event_name=EventName.FEATURE_VECTOR_READY,
        correlation_id=getattr(request.state, "correlation_id", ""),
        payload={"symbol": symbol, "vector": last_row},
    )
    stream_id = bus.publish("feature.vector.ready", event)
    return {
        "stream": "feature.vector.ready",
        "stream_id": stream_id,
        "feature_count": len(last_row),
    }
