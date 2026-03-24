from __future__ import annotations

import logging
import os
import signal
import time
from uuid import uuid4

from backend.src.platform.config import settings
from backend.src.platform.db import Database
from backend.src.platform.events import EventType, TradingEvent
from backend.src.platform.logging import setup_structured_logging
from backend.src.platform.observability import increment_error, increment_metric
from backend.src.platform.queue import RedisStreamQueue
from backend.src.platform.repository import (
    ensure_schema,
    get_latest_portfolio,
    insert_order,
    insert_portfolio_snapshot,
    insert_trade,
    persist_event,
)

logger = logging.getLogger(__name__)


class ExecutionEngineWorker:
    def __init__(self, consumer_name: str):
        self.consumer_name = consumer_name
        self.db = Database(settings.database_url_value)
        self.queue = RedisStreamQueue(settings.redis_url)
        self.running = True

    def _place_order_with_retry(self, event: TradingEvent) -> tuple[bool, str]:
        attempts = settings.execution_retry_limit
        delay = settings.execution_retry_delay_seconds
        payload = event.payload
        order_id = str(uuid4())

        for attempt in range(1, attempts + 1):
            try:
                inserted = insert_order(
                    db=self.db,
                    order_id=order_id,
                    idempotency_key=event.idempotency_key or event.event_id,
                    symbol=payload["symbol"],
                    side=payload["side"],
                    quantity=float(payload["quantity"]),
                    price=float(payload["price"]),
                    status="filled",
                )
                if not inserted:
                    return True, "already_processed"
                return True, f"filled:{order_id}"
            except Exception as exc:
                if attempt >= attempts:
                    return False, str(exc)
                time.sleep(delay)
        return False, "unknown"

    def run(self) -> None:
        setup_structured_logging(settings.log_level)
        ensure_schema(self.db)
        self.queue.ensure_group("events.execution", "execution-engine")

        logger.info("execution_engine_started")
        while self.running:
            records = self.queue.consume_group(
                stream="events.execution",
                group="execution-engine",
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
                    increment_metric(self.queue, "execution_events_received")

                    if event.event_type != EventType.SIGNAL_APPROVED:
                        ack_ids.append(message_id)
                        continue

                    logger.info(
                        "pipeline_stage stage=execution_event_received message_id=%s event_id=%s symbol=%s side=%s",
                        message_id,
                        event.event_id,
                        event.payload.get("symbol"),
                        event.payload.get("side"),
                    )

                    ok, reason = self._place_order_with_retry(event)
                    next_type = EventType.ORDER_FILLED if ok else EventType.ORDER_FAILED
                    order_id = ""
                    if reason.startswith("filled:"):
                        order_id = reason.split(":", 1)[1]
                        reason = "filled"
                    out_event = TradingEvent(
                        event_type=next_type,
                        payload={
                            **event.payload,
                            "reason": reason,
                            "order_id": order_id,
                            "parent_event_id": event.event_id,
                        },
                        source="execution-engine",
                        idempotency_key=event.idempotency_key or event.event_id,
                    )
                    self.queue.publish("events.execution", out_event.to_dict())
                    persist_event(self.db, out_event.to_dict())
                    logger.info(
                        "pipeline_stage stage=trade_executed event_id=%s parent_event_id=%s status=%s reason=%s",
                        out_event.event_id,
                        event.event_id,
                        out_event.event_type.value,
                        reason,
                    )

                    if ok:
                        trade_inserted = insert_trade(
                            db=self.db,
                            trade_id=out_event.event_id,
                            order_id=order_id,
                            parent_event_id=event.event_id,
                            symbol=str(event.payload.get("symbol", "")),
                            side=str(event.payload.get("side", "")),
                            quantity=float(event.payload.get("quantity", 0.0) or 0.0),
                            price=float(event.payload.get("price", 0.0) or 0.0),
                            notional=float(event.payload.get("notional", 0.0) or 0.0),
                            status="filled",
                            reason=reason,
                            payload=out_event.payload,
                        )
                        if trade_inserted:
                            logger.info(
                                "TRADE INSERTED stage=trade_persist trade_id=%s order_id=%s symbol=%s side=%s quantity=%s",
                                out_event.event_id,
                                order_id,
                                event.payload.get("symbol"),
                                event.payload.get("side"),
                                event.payload.get("quantity"),
                            )

                        notional_raw = event.payload.get("notional")
                        if notional_raw is None:
                            logger.error("execution_missing_notional event_id=%s message_id=%s", event.event_id, message_id)
                        else:
                            try:
                                notional = float(notional_raw)
                                signed = 1.0 if str(event.payload.get("side", "")).lower() == "buy" else -1.0
                            except (TypeError, ValueError):
                                logger.error("execution_invalid_notional event_id=%s message_id=%s", event.event_id, message_id)
                            else:
                                latest = get_latest_portfolio(self.db)
                                cash = float(latest.get("cash", 100000.0) or 100000.0)
                                exposure = float(latest.get("exposure", 0.0) or 0.0)
                                realized_pnl = float(latest.get("realized_pnl", 0.0) or 0.0)
                                next_exposure = exposure + signed * notional
                                next_cash = cash - signed * notional
                                insert_portfolio_snapshot(
                                    self.db,
                                    cash=next_cash,
                                    exposure=next_exposure,
                                    realized_pnl=realized_pnl,
                                )
                                logger.info(
                                    "pipeline_stage stage=portfolio_updated event_id=%s cash=%s exposure=%s realized_pnl=%s",
                                    out_event.event_id,
                                    next_cash,
                                    next_exposure,
                                    realized_pnl,
                                )
                        increment_metric(self.queue, "trades_executed")
                    else:
                        increment_metric(self.queue, "execution_failures")
                    ack_ids.append(message_id)
                except Exception as exc:
                    increment_error(self.queue, "execution_engine")
                    logger.exception(
                        "execution_message_processing_failed message_id=%s event_id=%s err=%s",
                        message_id,
                        getattr(event, "event_id", "unknown"),
                        exc,
                    )
                    ack_ids.append(message_id)

            self.queue.ack("events.execution", "execution-engine", ack_ids)

    def shutdown(self) -> None:
        self.running = False
        self.queue.close()
        self.db.close()


def main() -> None:
    service_name = str(os.getenv("SERVICE_NAME", "execution-engine")).strip() or "execution-engine"
    instance = str(os.getenv("SERVICE_INSTANCE_ID", os.getenv("HOSTNAME", ""))).strip()
    worker_id = f"{service_name}-{instance}" if instance else f"exec-{uuid4().hex[:8]}"
    worker = ExecutionEngineWorker(worker_id)
    signal.signal(signal.SIGINT, lambda *_: worker.shutdown())
    signal.signal(signal.SIGTERM, lambda *_: worker.shutdown())
    worker.run()


if __name__ == "__main__":
    main()
