"""Versioned event envelope and payload schemas for inter-service messaging."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0.0"


class EventName(str, Enum):
    MARKET_BAR_CLOSED = "market.bar.closed"
    FEATURE_VECTOR_READY = "feature.vector.ready"
    MODEL_INFERENCE_COMPLETED = "model.inference.completed"
    SIGNAL_GENERATED = "signal.generated"
    ORDER_INTENT_CREATED = "order.intent.created"
    RISK_DECISION = "risk.decision"
    ORDER_EXECUTED = "order.executed"
    PORTFOLIO_UPDATED = "portfolio.updated"


class EventEnvelope(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    correlation_id: str = Field(default_factory=lambda: uuid4().hex[:16])
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    schema_version: str = Field(default=SCHEMA_VERSION)
    source: str
    event_name: EventName
    payload: Dict[str, Any]


class PredictionRequest(BaseModel):
    symbol: str = "BTC/USDT"
    horizon: int = Field(default=5, ge=1, le=60)
    correlation_id: Optional[str] = None


class RiskCheckRequest(BaseModel):
    symbol: str
    side: str
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    volatility: float = Field(default=0.0, ge=0)
    correlation_id: Optional[str] = None


class OrderIntentRequest(BaseModel):
    symbol: str
    side: str
    quantity: float = Field(gt=0)
    order_type: str = "market"
    limit_price: Optional[float] = None
    correlation_id: Optional[str] = None
