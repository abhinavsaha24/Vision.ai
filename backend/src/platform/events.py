from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class EventType(str, Enum):
    MARKET_TICK = "market.tick"
    STRATEGY_START = "strategy.start"
    STRATEGY_STOP = "strategy.stop"
    SIGNAL_GENERATED = "signal.generated"
    SIGNAL_APPROVED = "signal.approved"
    RISK_REJECTED = "risk.rejected"
    ORDER_SUBMITTED = "order.submitted"
    ORDER_FILLED = "order.filled"
    ORDER_FAILED = "order.failed"
    PORTFOLIO_SNAPSHOT = "portfolio.snapshot"


@dataclass
class TradingEvent:
    event_type: EventType
    payload: dict[str, Any]
    source: str
    idempotency_key: str = ""
    event_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["event_type"] = self.event_type.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TradingEvent":
        if "event_type" not in data:
            raise ValueError("missing_required_field:event_type")
        raw_event_type = data.get("event_type")
        try:
            event_type = EventType(str(raw_event_type))
        except Exception as exc:
            raise ValueError(f"invalid_event_type:{raw_event_type}") from exc

        source = str(data.get("source", "") or "").strip()
        if not source:
            raise ValueError("missing_required_field:source")

        return cls(
            event_type=event_type,
            payload=data.get("payload", {}),
            source=source,
            idempotency_key=data.get("idempotency_key", ""),
            event_id=data.get("event_id", str(uuid4())),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
        )
