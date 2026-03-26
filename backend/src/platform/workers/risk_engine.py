from __future__ import annotations

import logging
import os
import signal
from uuid import uuid4

from backend.src.platform.config import settings
from backend.src.platform.db import Database
from backend.src.platform.events import EventType, TradingEvent
from backend.src.platform.logging import setup_structured_logging
from backend.src.platform.observability import increment_error, increment_metric
from backend.src.platform.queue import RedisStreamQueue
from backend.src.platform.repository import ensure_schema, get_current_drawdown_pct, get_latest_portfolio, persist_event
from backend.src.platform.risk_policy import RiskPolicy

logger = logging.getLogger(__name__)


class RiskEngineWorker:
    def __init__(self, consumer_name: str):
        self.consumer_name = consumer_name
        self.db = Database(settings.database_url_value)
        self.queue = RedisStreamQueue(settings.redis_url)
        self.policy = RiskPolicy(
            max_position_size=settings.max_position_size,
            max_notional_exposure=settings.max_notional_exposure,
            max_drawdown_pct=settings.max_drawdown_pct,
        )
        self.running = True

    def run(self) -> None:
        setup_structured_logging(settings.log_level)
        ensure_schema(self.db)
        self.queue.ensure_group("events.trading", "risk-engine")

        logger.info("risk_engine_started")
        while self.running:
            records = self.queue.consume_group(
                stream="events.trading",
                group="risk-engine",
                consumer=self.consumer_name,
                count=50,
                block_ms=settings.queue_block_ms,
            )
            ack_ids: list[str] = []

            for message_id, raw in records:
                event: TradingEvent | None = None
                try:
                    event = TradingEvent.from_dict(raw)
                    persist_event(self.db, event.to_dict())
                    increment_metric(self.queue, "risk_events_received")
                    if event.event_type != EventType.SIGNAL_GENERATED:
                        ack_ids.append(message_id)
                        continue

                    logger.info(
                        "pipeline_stage stage=risk_event_received message_id=%s event_id=%s symbol=%s side=%s",
                        message_id,
                        event.event_id,
                        event.payload.get("symbol"),
                        event.payload.get("side"),
                    )

                    portfolio = get_latest_portfolio(self.db)
                    if portfolio is None or "exposure" not in portfolio:
                        logger.warning("risk_worker_missing_portfolio defaulting_exposure_zero")
                        current_exposure = 0.0
                    else:
                        current_exposure = float(portfolio.get("exposure", 0.0) or 0.0)

                    notional_raw = event.payload.get("notional")
                    qty_raw = event.payload.get("quantity")
                    if notional_raw is None or qty_raw is None:
                        raise ValueError("risk_payload_missing_notional_or_quantity")
                    requested_notional = float(notional_raw)
                    requested_qty = float(qty_raw)
                    side = str(event.payload.get("side", "")).lower()

                    current_drawdown_pct = get_current_drawdown_pct(self.db)

                    check = self.policy.evaluate(
                        requested_qty=requested_qty,
                        requested_notional=requested_notional,
                        side=side,
                        current_exposure=current_exposure,
                        current_drawdown_pct=current_drawdown_pct,
                    )

                    logger.info(
                        "pipeline_stage stage=risk_decision event_id=%s approved=%s reason=%s exposure=%s drawdown_pct=%s",
                        event.event_id,
                        check.approved,
                        check.reason,
                        current_exposure,
                        current_drawdown_pct,
                    )

                    next_type = EventType.SIGNAL_APPROVED if check.approved else EventType.RISK_REJECTED
                    next_event = TradingEvent(
                        event_type=next_type,
                        payload={
                            **event.payload,
                            "reason": check.reason,
                            "parent_event_id": event.event_id,
                        },
                        source="risk-engine",
                        idempotency_key=event.idempotency_key or event.event_id,
                    )
                    self.queue.publish("events.execution", next_event.to_dict())
                    persist_event(self.db, next_event.to_dict())
                    if check.approved:
                        increment_metric(self.queue, "risk_approved")
                    else:
                        increment_metric(self.queue, "risk_rejected")

                    ack_ids.append(message_id)
                except Exception as exc:
                    increment_error(self.queue, "risk_engine")
                    logger.exception("risk_worker_message_failed message_id=%s raw=%s err=%s", message_id, raw, exc)
                    fail_event = TradingEvent(
                        event_type=EventType.RISK_REJECTED,
                        payload={
                            "reason": str(exc),
                            "raw": raw,
                            "parent_event_id": getattr(event, "event_id", ""),
                        },
                        source="risk-engine",
                        idempotency_key=(getattr(event, "idempotency_key", "") or getattr(event, "event_id", "") or message_id),
                    )
                    persist_event(self.db, fail_event.to_dict())
                    self.queue.publish("events.dead-letter", fail_event.to_dict())
                    ack_ids.append(message_id)

            self.queue.ack("events.trading", "risk-engine", ack_ids)

    def shutdown(self) -> None:
        self.running = False
        self.queue.close()
        self.db.close()


def main() -> None:
    service_name = str(os.getenv("SERVICE_NAME", "risk-engine")).strip() or "risk-engine"
    instance = str(os.getenv("SERVICE_INSTANCE_ID", os.getenv("HOSTNAME", ""))).strip()
    worker_id = f"{service_name}-{instance}" if instance else f"risk-{uuid4().hex[:8]}"
    worker = RiskEngineWorker(worker_id)
    signal.signal(signal.SIGINT, lambda *_: worker.shutdown())
    signal.signal(signal.SIGTERM, lambda *_: worker.shutdown())
    worker.run()


if __name__ == "__main__":
    main()
