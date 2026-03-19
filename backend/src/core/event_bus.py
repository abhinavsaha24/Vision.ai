"""
Event-driven architecture for Vision-AI trading platform.

Provides a lightweight, in-process event bus with optional Redis Streams
backend for cross-process communication.

Usage:
    from backend.src.core.event_bus import event_bus, EventType

    # Subscribe
    async def on_market_data(event: Event):
        print(event.data)
    event_bus.subscribe(EventType.MARKET_DATA, on_market_data)

    # Publish
    await event_bus.publish(EventType.MARKET_DATA, {"symbol": "BTC/USDT", "price": 50000})
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger("vision-ai.events")


# ------------------------------------------------------------------
# Event Types
# ------------------------------------------------------------------


class EventType(str, Enum):
    """All event types in the trading system."""

    # Market data pipeline
    MARKET_DATA = "market_data"
    MARKET_DATA_ERROR = "market_data_error"

    # Signal pipeline
    FEATURES_COMPUTED = "features_computed"
    PREDICTION_GENERATED = "prediction_generated"
    SIGNAL_GENERATED = "signal_generated"

    # Trading pipeline
    TRADE_SUBMITTED = "trade_submitted"
    TRADE_EXECUTED = "trade_executed"
    TRADE_REJECTED = "trade_rejected"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"

    # Portfolio
    PORTFOLIO_UPDATE = "portfolio_update"
    EQUITY_UPDATE = "equity_update"

    # Risk
    RISK_ALERT = "risk_alert"
    KILL_SWITCH_ACTIVATED = "kill_switch_activated"
    DRAWDOWN_BREACH = "drawdown_breach"
    DAILY_LOSS_BREACH = "daily_loss_breach"

    # System
    SYSTEM_STATUS = "system_status"
    WORKER_HEARTBEAT = "worker_heartbeat"
    WORKER_ERROR = "worker_error"
    SERVICE_STARTED = "service_started"
    SERVICE_STOPPED = "service_stopped"


# ------------------------------------------------------------------
# Event
# ------------------------------------------------------------------


@dataclass
class Event:
    """An event flowing through the system."""

    event_type: EventType
    data: Dict[str, Any]
    timestamp: str = ""
    source: str = ""
    event_id: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.event_id:
            self.event_id = f"{self.event_type.value}_{int(time.time() * 1000)}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "data": self.data,
            "timestamp": self.timestamp,
            "source": self.source,
            "event_id": self.event_id,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Event":
        return cls(
            event_type=EventType(d["event_type"]),
            data=d.get("data", {}),
            timestamp=d.get("timestamp", ""),
            source=d.get("source", ""),
            event_id=d.get("event_id", ""),
        )


# Type alias for event handlers
EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


# ------------------------------------------------------------------
# EventBus
# ------------------------------------------------------------------


class EventBus:
    """
    Lightweight async event bus.

    - In-process: uses asyncio.Queue per subscriber
    - Supports both sync and async handlers
    - Optional Redis Streams backend for cross-process events
    """

    def __init__(self, max_history: int = 1000):
        self._subscribers: Dict[EventType, List[EventHandler]] = defaultdict(list)
        self._history: List[Event] = []
        self._max_history = max_history
        self._metrics = {
            "published": 0,
            "delivered": 0,
            "errors": 0,
        }

    # ---- Subscribe ----

    def subscribe(self, event_type: EventType, handler: EventHandler):
        """Subscribe a handler to an event type."""
        self._subscribers[event_type].append(handler)
        logger.debug("Subscribed {handler.__name__} to %s", event_type.value)

    def subscribe_all(self, handler: EventHandler):
        """Subscribe a handler to ALL event types."""
        for et in EventType:
            self._subscribers[et].append(handler)

    def unsubscribe(self, event_type: EventType, handler: EventHandler):
        """Remove a handler from an event type."""
        if handler in self._subscribers[event_type]:
            self._subscribers[event_type].remove(handler)

    # ---- Publish ----

    async def publish(
        self, event_type: EventType, data: Dict[str, Any], source: str = ""
    ) -> Event:
        """Publish an event to all subscribers."""
        event = Event(event_type=event_type, data=data, source=source)

        self._metrics["published"] += 1

        # Store in history
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history // 2 :]

        # Deliver to subscribers
        handlers = self._subscribers.get(event_type, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
                self._metrics["delivered"] += 1
            except Exception as e:
                self._metrics["errors"] += 1
                logger.error("Event handler error for {event_type.value}: %s", e)

        return event

    def publish_sync(
        self, event_type: EventType, data: Dict[str, Any], source: str = ""
    ) -> Event:
        """Synchronous publish — creates event without delivering to async handlers.
        Useful for logging/metrics from sync code."""
        event = Event(event_type=event_type, data=data, source=source)
        self._metrics["published"] += 1
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history // 2 :]
        return event

    # ---- Query ----

    def get_recent_events(
        self, event_type: Optional[EventType] = None, limit: int = 50
    ) -> List[Dict]:
        """Get recent events, optionally filtered by type."""
        events = self._history
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return [e.to_dict() for e in events[-limit:]]

    def get_metrics(self) -> Dict:
        """Get event bus metrics."""
        return {
            **self._metrics,
            "subscriber_count": sum(len(h) for h in self._subscribers.values()),
            "history_size": len(self._history),
            "event_types_active": [
                et.value for et in EventType if self._subscribers.get(et)
            ],
        }


# ------------------------------------------------------------------
# Global singleton
# ------------------------------------------------------------------

event_bus = EventBus()
