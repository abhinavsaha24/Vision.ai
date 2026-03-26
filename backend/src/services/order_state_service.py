"""Order state authority service with in-memory lifecycle state map."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import BaseModel

from backend.src.services.shared.app_factory import create_service_app

app = create_service_app("order-state-service")
_orders: dict[str, dict] = {}


class OrderStateUpdate(BaseModel):
    order_id: str
    status: str
    reason: str | None = None


@app.post("/orders/state")
async def update_order_state(payload: OrderStateUpdate):
    prev = _orders.get(payload.order_id, {})
    _orders[payload.order_id] = {
        **prev,
        "order_id": payload.order_id,
        "status": payload.status,
        "reason": payload.reason,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    return _orders[payload.order_id]


@app.get("/orders/{order_id}")
async def get_order(order_id: str):
    order = _orders.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="order_not_found")
    return order
