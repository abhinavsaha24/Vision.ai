"""Execution gateway with idempotent intent registration and execution endpoint."""

from __future__ import annotations

from fastapi import HTTPException, Request

from backend.src.contracts.events import (EventEnvelope, EventName,
                                          OrderIntentRequest)
from backend.src.core.config import settings
from backend.src.core.event_stream import RedisStreamsBus
from backend.src.exchange.exchange_adapter import PaperAdapter
from backend.src.services.shared.app_factory import create_service_app

app = create_service_app("execution-gateway")
bus = RedisStreamsBus(url=settings.redis_url, enabled=settings.redis_enabled)
adapter = PaperAdapter(initial_cash=100000.0)
_intents: dict[str, dict] = {}


@app.post("/orders/intent")
async def create_intent(payload: OrderIntentRequest, request: Request):
    correlation_id = payload.correlation_id or getattr(
        request.state, "correlation_id", ""
    )
    intent_key = f"{correlation_id}:{payload.symbol}:{payload.side}:{payload.quantity}:{payload.order_type}"
    if intent_key in _intents:
        return {"status": "duplicate", "intent": _intents[intent_key]}

    intent = payload.model_dump()
    intent["intent_id"] = intent_key
    _intents[intent_key] = intent
    event = EventEnvelope(
        source="execution-gateway",
        event_name=EventName.ORDER_INTENT_CREATED,
        correlation_id=correlation_id,
        payload=intent,
    )
    stream_id = bus.publish("order.intent.created", event)
    return {"status": "accepted", "intent": intent, "stream_id": stream_id}


@app.post("/orders/execute/{intent_id}")
async def execute_intent(intent_id: str, request: Request):
    intent = _intents.get(intent_id)
    if not intent:
        raise HTTPException(status_code=404, detail="intent_not_found")

    side = intent["side"].lower()
    if side not in {"buy", "sell"}:
        raise HTTPException(status_code=400, detail="invalid_side")

    price = intent.get("limit_price") or 1.0
    order = adapter.place_market_order(
        intent["symbol"], side, intent["quantity"], price=price
    )
    event = EventEnvelope(
        source="execution-gateway",
        event_name=EventName.ORDER_EXECUTED,
        correlation_id=getattr(request.state, "correlation_id", ""),
        payload={
            "intent_id": intent_id,
            "order_id": order.order_id,
            "status": order.status,
            "symbol": order.symbol,
            "side": order.side,
            "quantity": order.quantity,
            "filled_price": order.filled_price,
        },
    )
    stream_id = bus.publish("order.executed", event)
    return {"order": order.__dict__, "stream_id": stream_id}
