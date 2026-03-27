from __future__ import annotations

import logging
import os
from uuid import uuid4

from backend.src.platform.config import settings
from backend.src.platform.alpha_engine import AlphaEngine
from backend.src.platform.db import Database
from backend.src.platform.event_bus import create_event_bus
from backend.src.platform.events import EventType, TradingEvent
from backend.src.platform.logging import setup_structured_logging
from backend.src.platform.observability import increment_error, increment_metric
from backend.src.platform.portfolio_allocator import AllocationInput, PortfolioAllocator
from backend.src.platform.repository import (
    ensure_schema,
    get_latest_portfolio,
    insert_signal,
    is_strategy_enabled,
    persist_event,
)
from backend.src.platform.signal_orchestrator import SignalOrchestrator

logger = logging.getLogger(__name__)


class TradingEngineWorker:
    def __init__(self, consumer_name: str):
        self.consumer_name = consumer_name
        self.db = Database(settings.database_url_value)
        self.queue = create_event_bus()
        self.alpha_engine = AlphaEngine()
        self.signal_orchestrator = SignalOrchestrator()
        self.allocator = PortfolioAllocator()
        self.running = True
        self._market_tick_counter = 0

    def _build_forced_signal(self, market_tick: dict[str, object], parent_event_id: str) -> TradingEvent | None:
        try:
            symbol = str(market_tick.get("symbol", "")).strip()
            price = float(market_tick.get("price", 0.0) or 0.0)
        except Exception:
            return None
        if not symbol or price <= 0.0:
            return None

        notional = float(settings.force_test_trade_notional)
        quantity = notional / max(price, 1e-9)
        return TradingEvent(
            event_type=EventType.SIGNAL_GENERATED,
            payload={
                "symbol": symbol,
                "side": "buy",
                "quantity": round(quantity, 8),
                "price": round(price, 4),
                "notional": round(notional, 4),
                "stop_loss": round(price * 0.995, 4),
                "take_profit": round(price * 1.01, 4),
                "confidence": 0.99,
                "score": 0.99,
                "signal": "forced_validation",
                "flow_score": 1.0,
                "structure_score": 1.0,
                "volatility_score": 0.5,
                "flow_alignment": "aligned",
                "regime": "validation",
                "timeframe": "validation",
                "selected_edge": "forced_validation_edge",
                "edge_stats": {
                    "forced_validation_edge": {
                        "trades": 1,
                        "expectancy": 1.0,
                        "profit_factor": 10.0,
                        "t_stat": 10.0,
                    }
                },
                "allocator": {
                    "positions": {symbol: 0.01},
                    "meta": {"status": "forced_validation"},
                },
                "parent_event_id": parent_event_id,
                "force_test_trade": True,
            },
            source="trading-engine",
            idempotency_key=f"forced-signal:{symbol}:{parent_event_id}",
        )

    def _persist_signal_record(self, signal_event: TradingEvent, parent_event_id: str) -> None:
        payload = signal_event.payload
        inserted = insert_signal(
            db=self.db,
            signal_id=signal_event.event_id,
            parent_event_id=parent_event_id,
            symbol=str(payload.get("symbol", "")),
            side=str(payload.get("side", "")),
            quantity=float(payload.get("quantity", 0.0) or 0.0),
            price=float(payload.get("price", 0.0) or 0.0),
            notional=float(payload.get("notional", 0.0) or 0.0),
            confidence=float(payload.get("confidence", 0.0) or 0.0),
            score=float(payload.get("score", 0.0) or 0.0),
            payload=payload,
        )
        if inserted:
            logger.info(
                "SIGNAL INSERTED stage=signal_persist signal_id=%s parent_event_id=%s symbol=%s side=%s quantity=%s",
                signal_event.event_id,
                parent_event_id,
                payload.get("symbol"),
                payload.get("side"),
                payload.get("quantity"),
            )

    def run(self) -> None:
        setup_structured_logging(settings.log_level)
        ensure_schema(self.db)
        self.queue.ensure_group("events.trading", "trading-engine")

        logger.info("trading_engine_started")
        while self.running:
            records = self.queue.consume_group(
                topic="events.trading",
                group="trading-engine",
                consumer=self.consumer_name,
                count=50,
                block_ms=settings.queue_block_ms,
            )
            ack_ids: list[str] = []

            for message_id, raw in records:
                try:
                    event = TradingEvent.from_dict(raw)
                    persist_event(self.db, event.to_dict())
                    increment_metric(self.queue, "events_received")
                    logger.info(
                        "pipeline_stage stage=market_event_received message_id=%s event_id=%s event_type=%s source=%s",
                        message_id,
                        event.event_id,
                        event.event_type.value,
                        event.source,
                    )

                    if event.event_type == EventType.MARKET_TICK:
                        increment_metric(self.queue, "market_events")
                        self._market_tick_counter += 1
                        strategy_name = event.payload.get("strategy_name", "default")
                        if not is_strategy_enabled(self.db, strategy_name):
                            logger.info(
                                "pipeline_stage stage=market_event_skipped reason=strategy_disabled strategy=%s event_id=%s",
                                strategy_name,
                                event.event_id,
                            )
                            ack_ids.append(message_id)
                            continue

                        alpha_signal = self.alpha_engine.on_tick(event.payload, strategy_name)
                        signal: TradingEvent | None = None
                        if alpha_signal is not None:
                            orchestrated = self.signal_orchestrator.evaluate(event.payload, alpha_signal)
                            if not orchestrated.get("approved", False):
                                logger.info(
                                    "pipeline_stage stage=signal_orchestrator_reject event_id=%s unified_score=%s",
                                    event.event_id,
                                    orchestrated.get("unified_score"),
                                )
                                ack_ids.append(message_id)
                                continue

                            latest_portfolio = get_latest_portfolio(self.db)
                            deployable_notional = min(
                                float(latest_portfolio.get("cash", 0.0) or 0.0),
                                settings.max_notional_exposure,
                            )
                            selected_edge = str(alpha_signal.get("selected_edge") or "")
                            selected_stats = (alpha_signal.get("edge_stats", {}) or {}).get(selected_edge, {}) or {}
                            allocation = self.allocator.allocate(
                                AllocationInput(
                                    edges=[
                                        {
                                            "edge_id": selected_edge,
                                            "direction": "long" if alpha_signal["side"] == "buy" else "short",
                                            "confidence_score": float(alpha_signal.get("confidence", 0.0) or 0.0),
                                            "sample_size": float(selected_stats.get("trades", 0.0) or 0.0),
                                            "asset_coverage": [alpha_signal["symbol"]],
                                            "in_sample_metrics": {
                                                "t_stat": float(selected_stats.get("t_stat", 0.0) or 0.0),
                                            },
                                        }
                                    ]
                                )
                            )

                            target_exposure = float(allocation.positions.get(alpha_signal["symbol"], 0.0) or 0.0)
                            try:
                                base_fraction = float(alpha_signal.get("position_fraction", 0.0) or 0.0)
                            except (TypeError, ValueError):
                                base_fraction = 0.0
                            position_fraction = max(
                                0.0,
                                abs(target_exposure)
                                * base_fraction
                                * float(orchestrated.get("unified_score", 0.0) or 0.0),
                            )
                            notional = max(0.0, deployable_notional * position_fraction)
                            try:
                                price = float(alpha_signal.get("price", 0.0) or 0.0)
                            except (TypeError, ValueError):
                                price = 0.0
                            if price < 1e-3:
                                logger.warning("trading_engine_invalid_alpha_price signal=%s", alpha_signal)
                                ack_ids.append(message_id)
                                continue
                            quantity = notional / price

                            if quantity > 0 and notional > 0:
                                signal = TradingEvent(
                                    event_type=EventType.SIGNAL_GENERATED,
                                    payload={
                                        "symbol": alpha_signal["symbol"],
                                        "side": alpha_signal["side"],
                                        "quantity": round(quantity, 8),
                                        "price": round(float(price), 4),
                                        "notional": round(notional, 4),
                                        "stop_loss": round(float(alpha_signal["stop_loss"]), 4),
                                        "take_profit": round(float(alpha_signal["take_profit"]), 4),
                                        "confidence": round(float(alpha_signal["confidence"]), 4),
                                        "score": round(float(alpha_signal["score"]), 4),
                                        "signal": str(alpha_signal.get("meta", {}).get("signal", "neutral")),
                                        "flow_score": float(alpha_signal.get("meta", {}).get("flow_score", 0.0) or 0.0),
                                        "structure_score": float(alpha_signal.get("meta", {}).get("structure_score", 0.0) or 0.0),
                                        "volatility_score": float(alpha_signal.get("meta", {}).get("volatility_score", 0.0) or 0.0),
                                        "flow_alignment": str(alpha_signal.get("meta", {}).get("flow_alignment", "neutral")),
                                        "regime": alpha_signal["regime"],
                                        "timeframe": alpha_signal["timeframe"],
                                        "selected_edge": alpha_signal.get("selected_edge"),
                                        "edge_stats": alpha_signal["edge_stats"],
                                        "allocator": {
                                            "positions": allocation.positions,
                                            "meta": allocation.meta,
                                        },
                                        "unified_score": float(orchestrated.get("unified_score", 0.0) or 0.0),
                                        "signal_orchestrator": orchestrated,
                                    },
                                    source="trading-engine",
                                    idempotency_key=(
                                        f"signal:{alpha_signal['symbol']}:{alpha_signal['ts']}:{alpha_signal['side']}"
                                    ),
                                )
                        elif (
                            settings.force_test_trade
                            and self._market_tick_counter % int(settings.force_test_trade_every_n_ticks) == 0
                        ):
                            signal = self._build_forced_signal(event.payload, event.event_id)

                        if signal is not None:
                            persist_event(self.db, signal.to_dict())
                            self._persist_signal_record(signal, event.event_id)
                            self.queue.publish("events.trading", signal.to_dict())
                            increment_metric(self.queue, "signals_generated")
                            logger.info(
                                "pipeline_stage stage=signal_generated event_id=%s parent_event_id=%s symbol=%s side=%s notional=%s",
                                signal.event_id,
                                event.event_id,
                                signal.payload.get("symbol"),
                                signal.payload.get("side"),
                                signal.payload.get("notional"),
                            )
                        else:
                            logger.info(
                                "pipeline_stage stage=signal_not_generated event_id=%s symbol=%s",
                                event.event_id,
                                event.payload.get("symbol"),
                            )

                    ack_ids.append(message_id)
                except Exception as exc:
                    increment_error(self.queue, "trading_engine")
                    logger.exception("trading_worker_message_failed message_id=%s raw=%s err=%s", message_id, raw, exc)
                    ack_ids.append(message_id)

            self.queue.ack("events.trading", "trading-engine", ack_ids)

    def shutdown(self) -> None:
        self.running = False
        self.queue.close()
        self.db.close()


def main() -> None:
    service_name = str(os.getenv("SERVICE_NAME", "trading-engine")).strip() or "trading-engine"
    instance = str(os.getenv("SERVICE_INSTANCE_ID", os.getenv("HOSTNAME", ""))).strip()
    worker_id = f"{service_name}-{instance}" if instance else f"trading-{uuid4().hex[:8]}"
    worker = TradingEngineWorker(worker_id)
    worker.run()


if __name__ == "__main__":
    main()
