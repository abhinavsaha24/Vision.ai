"""Model service exposing low-latency prediction and model metadata endpoints."""

from __future__ import annotations

from fastapi import Request

from backend.src.contracts.events import (EventEnvelope, EventName,
                                          PredictionRequest)
from backend.src.core.config import settings
from backend.src.core.event_stream import RedisStreamsBus
from backend.src.models.model_registry import ModelRegistry
from backend.src.models.predictor import Predictor
from backend.src.services.shared.app_factory import create_service_app

app = create_service_app("model-service")
bus = RedisStreamsBus(url=settings.redis_url, enabled=settings.redis_enabled)
predictor = Predictor()
registry = ModelRegistry()


@app.post("/predict")
async def predict(payload: PredictionRequest, request: Request):
    preds = predictor.predict_symbol(payload.symbol, payload.horizon)
    event = EventEnvelope(
        source="model-service",
        event_name=EventName.MODEL_INFERENCE_COMPLETED,
        correlation_id=payload.correlation_id
        or getattr(request.state, "correlation_id", ""),
        payload={
            "symbol": payload.symbol,
            "horizon": payload.horizon,
            "predictions": preds,
        },
    )
    stream_id = bus.publish("model.inference.completed", event)
    return {"predictions": preds, "stream_id": stream_id}


@app.get("/model/version")
async def model_version():
    return {
        "active_version": registry.active_version,
        "versions": registry.get_all_versions(),
    }


@app.get("/model/metrics")
async def model_metrics():
    return {"performance_history": registry.get_performance_history()}
