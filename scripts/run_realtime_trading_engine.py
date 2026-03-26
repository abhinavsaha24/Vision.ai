from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import cast
from urllib.parse import quote_plus
from uuid import uuid4, uuid5, NAMESPACE_URL

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.src.platform.db import Database
from backend.src.platform.events import EventType, TradingEvent
from backend.src.platform.live.engine import RealTimeExecutionAlphaEngine
from backend.src.platform.live.types import EngineConfig, ExecutionReport, SignalDecision
from backend.src.platform.observability import increment_error, increment_metric, metrics_snapshot
from backend.src.platform.queue import RedisStreamQueue
from backend.src.platform.repository import (
    ensure_schema,
    get_latest_portfolio,
    insert_order,
    insert_portfolio_snapshot,
    insert_signal,
    insert_trade,
    persist_event,
)

logger = logging.getLogger("realtime_trading_engine")


class LivePersistenceRuntime:
    """Incremental sink from in-memory live bus -> Postgres + Redis metrics."""

    def __init__(self, engine: RealTimeExecutionAlphaEngine, db: Database, metrics_queue: RedisStreamQueue | None, metrics_interval_sec: float):
        self.engine = engine
        self.db = db
        self.metrics_queue = metrics_queue
        self.metrics_interval_sec = max(1.0, float(metrics_interval_sec))
        self.stop_event = asyncio.Event()

        self.signal_bus = self.engine.infrastructure.bus.subscribe("signal", maxsize=5000)
        self.execution_bus = self.engine.infrastructure.bus.subscribe("execution", maxsize=5000)

        self._tasks: list[asyncio.Task] = []
        self._signal_counter = 0
        self._exec_counter = 0
        self._inserted_signals = 0
        self._inserted_trades = 0
        self._pending_signal_ids: dict[str, deque[str]] = defaultdict(deque)

    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._signal_sink_loop()),
            asyncio.create_task(self._execution_sink_loop()),
            asyncio.create_task(self._metrics_loop()),
        ]

    async def stop(self) -> None:
        self.stop_event.set()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self.engine.infrastructure.bus.unsubscribe("signal", self.signal_bus)
        self.engine.infrastructure.bus.unsubscribe("execution", self.execution_bus)

    @staticmethod
    def _normalize_side(side: str) -> str:
        if side == "long":
            return "buy"
        if side == "short":
            return "sell"
        return side

    def _build_signal_id(self, signal: SignalDecision) -> str:
        self._signal_counter += 1
        raw = (
            f"live-signal:{signal.symbol}:{signal.ts_ms}:{signal.side}:{signal.event_type}:{signal.reason}:"
            f"{round(float(signal.score), 6)}:{self._signal_counter}"
        )
        return str(uuid5(NAMESPACE_URL, raw))

    def _build_trade_id(self, report: ExecutionReport, parent_signal_id: str) -> str:
        self._exec_counter += 1
        raw = (
            f"live-trade:{report.symbol}:{report.ts_ms}:{report.side}:{report.status}:"
            f"{round(float(report.fill_price), 6)}:{round(float(report.quantity), 8)}:{parent_signal_id}:{self._exec_counter}"
        )
        return str(uuid5(NAMESPACE_URL, raw))

    def _record_metric(self, name: str, value: float = 1.0) -> None:
        if self.metrics_queue is None:
            return
        try:
            increment_metric(self.metrics_queue, name, value)
        except Exception:
            return

    def _record_error(self, name: str, value: float = 1.0) -> None:
        if self.metrics_queue is None:
            return
        try:
            increment_error(self.metrics_queue, name, value)
        except Exception:
            return

    async def _signal_sink_loop(self) -> None:
        while not self.stop_event.is_set():
            symbol_for_log = ""
            signal_pulled = False
            try:
                signal = cast(SignalDecision, await self.signal_bus.get())
                signal_pulled = True
                symbol_for_log = signal.symbol
                side = self._normalize_side(str(signal.side).lower())
                score = max(0.0, min(1.0, float(signal.score)))
                notional = max(10.0, self.engine.config.max_position_notional * max(0.25, score))
                price_hint = float(signal.features.get("ref_price", 0.0) or 0.0)
                if price_hint <= 0.0:
                    logger.warning("live_signal_skip_invalid_price_hint symbol=%s signal=%s", signal.symbol, signal)
                    continue
                quantity = float(notional / max(price_hint, 1e-9))

                signal_id = self._build_signal_id(signal)
                event = TradingEvent(
                    event_type=EventType.SIGNAL_GENERATED,
                    payload={
                        "symbol": signal.symbol,
                        "side": side,
                        "quantity": quantity,
                        "price": price_hint,
                        "notional": notional,
                        "confidence": score,
                        "score": score,
                        "event_type": signal.event_type,
                        "reason": signal.reason,
                        "features": signal.features,
                        "ts_ms": signal.ts_ms,
                    },
                    source="live-realtime-engine",
                    idempotency_key=signal_id,
                    event_id=signal_id,
                )

                persist_event(self.db, event.to_dict())
                inserted = insert_signal(
                    db=self.db,
                    signal_id=signal_id,
                    parent_event_id="",
                    symbol=signal.symbol,
                    side=side,
                    quantity=quantity,
                    price=price_hint,
                    notional=notional,
                    confidence=score,
                    score=score,
                    payload=event.payload,
                )
                if inserted:
                    self._inserted_signals += 1
                    self._pending_signal_ids[signal.symbol].append(signal_id)
                    self._record_metric("signals_generated", 1.0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._record_error("live_signal_sink", 1.0)
                logger.warning("live_signal_sink_error err=%s signal=%s", exc, symbol_for_log)
            finally:
                if signal_pulled:
                    self.signal_bus.task_done()

    async def _execution_sink_loop(self) -> None:
        tradable_status = {"opened", "scaled", "closed", "partial_close"}
        while not self.stop_event.is_set():
            symbol_for_log = ""
            execution_pulled = False
            try:
                report = cast(ExecutionReport, await self.execution_bus.get())
                execution_pulled = True
                symbol_for_log = report.symbol
                symbol = str(report.symbol)
                pending = self._pending_signal_ids.get(symbol)
                explicit_signal_id = str(getattr(report, "signal_id", "") or "")
                if explicit_signal_id:
                    parent_signal_id = explicit_signal_id
                    if pending and explicit_signal_id in pending:
                        pending.remove(explicit_signal_id)
                else:
                    parent_signal_id = pending.popleft() if pending else ""

                side = self._normalize_side(str(report.side).lower())
                execution_notional = float(max(0.0, report.quantity) * max(0.0, report.fill_price))

                if report.status in tradable_status and report.fill_price > 0.0 and report.quantity > 0.0:
                    order_id = str(uuid4())
                    idempotency = f"live-order:{parent_signal_id}:{report.ts_ms}:{report.status}"
                    order_inserted = insert_order(
                        db=self.db,
                        order_id=order_id,
                        idempotency_key=idempotency,
                        symbol=symbol,
                        side=side,
                        quantity=float(report.quantity),
                        price=float(report.fill_price),
                        status="filled",
                        reason=str(report.detail or report.status),
                    )
                    if order_inserted:
                        trade_id = self._build_trade_id(report, parent_signal_id)
                        trade_payload = {
                            "source": "run_realtime_trading_engine",
                            "execution_status": report.status,
                            "fill_probability": float(report.fill_probability),
                            "slippage_bps": float(report.slippage_bps),
                            "simulated_latency_ms": float(report.simulated_latency_ms),
                            "requested_quantity": float(report.requested_quantity or report.quantity),
                            "filled_quantity": float(report.filled_quantity or report.quantity),
                            "parent_signal_id": parent_signal_id,
                        }
                        inserted = insert_trade(
                            db=self.db,
                            trade_id=trade_id,
                            order_id=order_id,
                            parent_event_id=parent_signal_id,
                            symbol=symbol,
                            side=side,
                            quantity=float(report.quantity),
                            price=float(report.fill_price),
                            notional=execution_notional,
                            status="filled",
                            reason=str(report.detail or report.status),
                            payload=trade_payload,
                        )
                        if inserted:
                            self._inserted_trades += 1
                            self._record_metric("trades_executed", 1.0)

                            latest = get_latest_portfolio(self.db)
                            cash = float(latest.get("cash", 100000.0) or 100000.0)
                            exposure = float(latest.get("exposure", 0.0) or 0.0)
                            realized_pnl = float(latest.get("realized_pnl", 0.0) or 0.0)
                            signed = 1.0 if side == "buy" else -1.0
                            next_exposure = exposure + (signed * execution_notional)
                            next_cash = cash - (signed * execution_notional)
                            next_realized_pnl = realized_pnl + float(report.pnl)
                            insert_portfolio_snapshot(self.db, next_cash, next_exposure, next_realized_pnl)
                else:
                    self._record_metric("execution_rejected", 1.0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._record_error("live_execution_sink", 1.0)
                logger.warning("live_execution_sink_error err=%s symbol=%s", exc, symbol_for_log)
            finally:
                if execution_pulled:
                    self.execution_bus.task_done()

    async def _metrics_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                await asyncio.sleep(self.metrics_interval_sec)
                if self.metrics_queue is not None:
                    snapshot = metrics_snapshot(self.metrics_queue)
                else:
                    snapshot = {"totals": {}, "trades_per_minute": 0.0}
                logger.info(
                    "live_runtime_metrics inserted_signals=%s inserted_trades=%s trades_per_minute=%s totals=%s",
                    self._inserted_signals,
                    self._inserted_trades,
                    snapshot.get("trades_per_minute", 0.0),
                    snapshot.get("totals", {}),
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._record_error("live_metrics", 1.0)
                logger.warning("live_metrics_error err=%s", exc)


def _resolve_database_url(cli_database_url: str) -> str:
    if cli_database_url.strip():
        return cli_database_url.strip()

    env_database_url = os.getenv("DATABASE_URL", "").strip()
    if env_database_url:
        return env_database_url

    db_host = os.getenv("DB_HOST", "localhost").strip()
    db_port = os.getenv("DB_PORT", "5432").strip()
    db_name = os.getenv("DB_NAME", "vision_core").strip()
    db_user = os.getenv("DB_USER", "vision").strip()
    db_password = os.getenv("DB_PASSWORD", "").strip()
    if not db_password:
        raise ValueError("missing DB_PASSWORD and DATABASE_URL; provide --database-url or set DB_PASSWORD")
    return f"postgresql://{quote_plus(db_user)}:{quote_plus(db_password)}@{db_host}:{db_port}/{db_name}"


async def _run(args: argparse.Namespace) -> None:
    db = Database(_resolve_database_url(args.database_url))
    queue: RedisStreamQueue | None = None
    redis_url = str(args.redis_url or os.getenv("REDIS_URL", "")).strip()
    if redis_url:
        queue = RedisStreamQueue(redis_url)

    ensure_schema(db)

    config = EngineConfig(
        symbol=args.symbol,
        use_depth_stream=bool(args.use_depth_stream),
        queue_size=max(500, int(args.queue_size)),
        log_path=args.log_path,
        max_position_notional=float(args.max_position_notional),
        max_symbol_notional=float(args.max_symbol_notional),
        max_concurrent_trades=max(1, int(args.max_concurrent_trades)),
        max_daily_trades=max(1, int(args.max_daily_trades)),
        max_daily_loss=float(args.max_daily_loss),
        execution_min_latency_ms=float(args.execution_min_latency_ms),
        execution_max_latency_ms=float(args.execution_max_latency_ms),
        execution_partial_fill_threshold=float(args.execution_partial_fill_threshold),
        execution_partial_fill_min_ratio=float(args.execution_partial_fill_min_ratio),
    )

    engine = RealTimeExecutionAlphaEngine(config)
    sink = LivePersistenceRuntime(engine=engine, db=db, metrics_queue=queue, metrics_interval_sec=float(args.metrics_interval_sec))

    await engine.start()
    await sink.start()

    started = time.time()
    try:
        while True:
            await asyncio.sleep(0.5)
            if args.duration_sec > 0 and (time.time() - started) >= float(args.duration_sec):
                logger.info("live_runtime_duration_reached duration_sec=%s", args.duration_sec)
                break
    finally:
        await sink.stop()
        await engine.stop()
        if queue is not None:
            queue.close()
        db.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run continuous realtime trading engine with incremental DB persistence")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--duration-sec", type=int, default=0, help="0 means run forever")
    parser.add_argument("--database-url", default="", help="Postgres URL; falls back to DATABASE_URL or DB_* env")
    parser.add_argument("--redis-url", default="", help="Redis URL for observability metrics")
    parser.add_argument("--log-path", default="data/live_alpha_signals.jsonl")
    parser.add_argument("--use-depth-stream", action="store_true", dest="use_depth_stream")
    parser.add_argument("--no-depth-stream", action="store_false", dest="use_depth_stream")
    parser.set_defaults(use_depth_stream=True)
    parser.add_argument("--queue-size", type=int, default=5000)
    parser.add_argument("--metrics-interval-sec", type=float, default=10.0)

    parser.add_argument("--max-position-notional", type=float, default=2500.0)
    parser.add_argument("--max-symbol-notional", type=float, default=3500.0)
    parser.add_argument("--max-concurrent-trades", type=int, default=1)
    parser.add_argument("--max-daily-trades", type=int, default=400)
    parser.add_argument("--max-daily-loss", type=float, default=450.0)

    parser.add_argument("--execution-min-latency-ms", type=float, default=8.0)
    parser.add_argument("--execution-max-latency-ms", type=float, default=55.0)
    parser.add_argument("--execution-partial-fill-threshold", type=float, default=0.18)
    parser.add_argument("--execution-partial-fill-min-ratio", type=float, default=0.35)
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    stop_requested = {"flag": False}

    def _request_stop(*_: object) -> None:
        stop_requested["flag"] = True
        for task in asyncio.all_tasks(loop):
            if task is not asyncio.current_task(loop=loop):
                task.cancel()

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    try:
        loop.run_until_complete(_run(args))
    except asyncio.CancelledError:
        logger.info("live_runtime_cancelled")
    except KeyboardInterrupt:
        logger.info("live_runtime_keyboard_interrupt")
    finally:
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()


if __name__ == "__main__":
    main()
