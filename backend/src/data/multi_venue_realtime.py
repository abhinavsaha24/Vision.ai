from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import websockets

if __package__ is None or __package__ == "":
    ROOT = Path(__file__).resolve().parents[3]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

from backend.src.data.microstructure_store import MicrostructureParquetStore
from backend.src.data.venue_adapters import NormalizedOrderBook, NormalizedTrade, VenueAdapter, build_adapter
from backend.src.platform.event_bus import create_event_bus
from backend.src.platform.events import EventType, TradingEvent

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IngestionStats:
    trades: int = 0
    orderbooks: int = 0
    reconnects: int = 0
    trade_gaps: int = 0
    orderbook_gaps: int = 0


class MarketEventPublisher:
    def __init__(self, redis_url: str, strategy_name: str = "default", publish_interval_ms: int = 1000):
        _ = redis_url
        self.queue = create_event_bus()
        self.strategy_name = strategy_name
        self.publish_interval_ms = max(100, int(publish_interval_ms))
        self._last_published_ms: dict[str, int] = {}

    def publish_market_tick(self, symbol: str, price: float, volume: float, ts_ms: int, source: str) -> bool:
        key = str(symbol).upper()
        prev = int(self._last_published_ms.get(key, 0))
        if prev and ts_ms - prev < self.publish_interval_ms:
            return False

        event = TradingEvent(
            event_type=EventType.MARKET_TICK,
            payload={
                "symbol": key,
                "price": float(price),
                "volume": float(max(0.0, volume)),
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts_ms / 1000.0)),
                "strategy_name": self.strategy_name,
            },
            source=source,
            idempotency_key=f"market:{source}:{key}:{ts_ms}",
        )
        self.queue.publish("events.trading", event.to_dict())
        self._last_published_ms[key] = ts_ms
        return True

    def close(self) -> None:
        self.queue.close()


class MultiVenueRealtimeIngestor:
    """Realtime normalized ingestion for multiple venues with durable local persistence."""

    def __init__(
        self,
        adapter: VenueAdapter,
        symbols: list[str],
        store: MicrostructureParquetStore,
        market_publisher: MarketEventPublisher | None = None,
    ):
        self.adapter = adapter
        self.symbols = list(symbols)
        self.store = store
        self.market_publisher = market_publisher
        self.stats = IngestionStats()
        self._running = False
        self._last_trade_seq: dict[str, int] = {}
        self._last_book_update: dict[str, int] = {}
        self._last_book_first: dict[str, int] = {}
        self._book_requires_bridge: dict[str, bool] = {}
        self._trade_recovery_pending: set[str] = set()
        self._book_recovery_pending: set[str] = set()
        self._started_at_ms = int(time.time() * 1000)
        self._message_queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue(maxsize=20000)
        self._connected_once: set[str] = set()

    async def run(self, stop_event: asyncio.Event) -> None:
        self._running = True
        urls = self.adapter.build_stream_urls(self.symbols)
        if not urls:
            logger.warning("no_stream_url_for_adapter venue=%s", self.adapter.name)
            return

        tasks = [asyncio.create_task(self._run_url(url, stop_event)) for url in urls]
        processor_task = asyncio.create_task(self._process_messages(stop_event))
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(stop_event))
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if not processor_task.done():
                processor_task.cancel()
            await asyncio.gather(processor_task, return_exceptions=True)
            if not heartbeat_task.done():
                heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
            self.store.flush()

    async def _heartbeat_loop(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set() and self._running:
            uptime_s = max(0.0, (int(time.time() * 1000) - self._started_at_ms) / 1000.0)
            logger.info(
                "capture_heartbeat venue=%s symbols=%s uptime_s=%.1f trades=%s books=%s reconnects=%s trade_gaps=%s orderbook_gaps=%s",
                self.adapter.name,
                ",".join(self.symbols),
                uptime_s,
                self.stats.trades,
                self.stats.orderbooks,
                self.stats.reconnects,
                self.stats.trade_gaps,
                self.stats.orderbook_gaps,
            )
            await asyncio.sleep(30.0)

    async def _run_url(self, url: str, stop_event: asyncio.Event) -> None:
        backoff = 1.0
        while not stop_event.is_set() and self._running:
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_queue=8192,
                ) as ws:
                    is_reconnect = url in self._connected_once
                    if url in self._connected_once:
                        self.stats.reconnects += 1
                    else:
                        self._connected_once.add(url)
                    if is_reconnect:
                        is_trade_stream = "@aggtrade" in str(url).lower()
                        is_depth_stream = "@depth" in str(url).lower()
                        for symbol in self.symbols:
                            stream_symbol = self.adapter.normalize_symbol(symbol).lower()
                            if stream_symbol not in str(url).lower():
                                continue
                            key = f"{self.adapter.name}:{self.adapter.normalize_symbol(symbol)}"
                            if is_trade_stream:
                                self._trade_recovery_pending.add(key)
                            if is_depth_stream:
                                self._book_recovery_pending.add(key)
                                # Force a fresh snapshot bridge after reconnect to re-anchor continuity.
                                self._last_book_update.pop(key, None)
                                self._last_book_first.pop(key, None)
                                self._book_requires_bridge[key] = True
                    logger.info("venue_ws_connected venue=%s url=%s", self.adapter.name, url)
                    backoff = 1.0

                    payload = self.adapter.build_subscribe_payload(self.symbols)
                    if payload is not None:
                        await ws.send(json.dumps(payload))
                        logger.info("venue_ws_subscribed venue=%s symbols=%s", self.adapter.name, ",".join(self.symbols))

                    async for raw in ws:
                        if stop_event.is_set() or not self._running:
                            break
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8", errors="ignore")
                        await self._message_queue.put((raw, int(time.time() * 1000)))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("venue_ws_reconnect venue=%s err=%s", self.adapter.name, exc)
                await asyncio.sleep(backoff)
                backoff = min(60.0, backoff * 2.0)

    async def _process_messages(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set() and self._running:
            try:
                raw, receive_ts_ms = await asyncio.wait_for(self._message_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            try:
                await self._handle_raw(raw, receive_ts_ms)
            finally:
                self._message_queue.task_done()

    async def _handle_raw(self, raw: str, receive_ts_ms: int) -> None:
        try:
            trades, books = self.adapter.parse_message(raw, receive_ts_ms)
        except Exception as exc:
            logger.debug("venue_message_parse_failed venue=%s err=%s", self.adapter.name, exc)
            return

        for trade in trades:
            should_append, _ = await self._check_trade_gap(trade)
            if not should_append:
                continue
            self.store.append_trade(trade)
            self.stats.trades += 1
            if self.market_publisher is not None:
                try:
                    published = self.market_publisher.publish_market_tick(
                        symbol=trade.symbol,
                        price=trade.price,
                        volume=trade.quantity,
                        ts_ms=int(trade.exchange_ts_ms),
                        source=f"capture-{trade.venue}",
                    )
                    if published:
                        logger.info(
                            "pipeline_stage stage=market_event_received source=capture-trade venue=%s symbol=%s price=%s qty=%s ts_ms=%s",
                            trade.venue,
                            trade.symbol,
                            trade.price,
                            trade.quantity,
                            trade.exchange_ts_ms,
                        )
                except Exception as exc:
                    logger.warning("market_event_publish_failed symbol=%s err=%s", trade.symbol, exc)

        # Event-time normalization: process orderbook deltas in exchange timestamp order.
        books = sorted(
            books,
            key=lambda x: (
                int(x.exchange_ts_ms),
                int(x.first_update_id or x.update_id or 0),
                int(x.update_id or 0),
            ),
        )
        for book in books:
            should_append, _ = self._check_orderbook_gap(book)
            if not should_append:
                continue
            self.store.append_orderbook(book)
            self.stats.orderbooks += 1
            logger.debug(
                "orderbook_update_received venue=%s symbol=%s update_id=%s first_update_id=%s bids=%s asks=%s",
                book.venue,
                book.symbol,
                int(book.update_id or 0),
                int(book.first_update_id or book.update_id or 0),
                len(book.bids),
                len(book.asks),
            )
            if self.market_publisher is not None and book.best_bid > 0 and book.best_ask > 0:
                mid_price = (float(book.best_bid) + float(book.best_ask)) / 2.0
                try:
                    published = self.market_publisher.publish_market_tick(
                        symbol=book.symbol,
                        price=mid_price,
                        volume=0.0,
                        ts_ms=int(book.exchange_ts_ms),
                        source=f"capture-{book.venue}",
                    )
                    if published:
                        logger.info(
                            "pipeline_stage stage=market_event_received source=capture-orderbook venue=%s symbol=%s price=%s ts_ms=%s",
                            book.venue,
                            book.symbol,
                            mid_price,
                            book.exchange_ts_ms,
                        )
                except Exception as exc:
                    logger.warning("market_event_publish_failed symbol=%s err=%s", book.symbol, exc)

    async def _check_trade_gap(self, row: NormalizedTrade) -> tuple[bool, bool]:
        if row.sequence_id is None:
            return True, False
        key = f"{row.venue}:{row.symbol}"
        if key in self._trade_recovery_pending:
            self._trade_recovery_pending.discard(key)
            self._last_trade_seq[key] = row.sequence_id
            logger.info(
                "trade_reconnect_baseline_reset venue=%s symbol=%s seq=%s",
                row.venue,
                row.symbol,
                row.sequence_id,
            )
            return True, False
        prev = self._last_trade_seq.get(key)
        if prev is not None and row.sequence_id <= prev:
            logger.debug(
                "trade_out_of_order_discarded venue=%s symbol=%s prev=%s cur=%s",
                row.venue,
                row.symbol,
                prev,
                row.sequence_id,
            )
            return False, False

        if prev is not None and row.sequence_id > prev + 1:
            self.stats.trade_gaps += 1
            logger.warning(
                "trade_gap_detected venue=%s symbol=%s prev=%s cur=%s",
                row.venue,
                row.symbol,
                prev,
                row.sequence_id,
            )
            recovered_to = prev
            try:
                recovered = self.adapter.backfill_trade_gap(
                    symbol=row.symbol,
                    from_sequence_id=prev,
                    to_sequence_id=int(row.sequence_id),
                    receive_ts_ms=int(row.receive_ts_ms),
                )
                expected = prev + 1
                for missing in recovered:
                    missing_seq = int(missing.sequence_id or 0)
                    if missing_seq != expected:
                        break
                    self.store.append_trade(missing)
                    self.stats.trades += 1
                    recovered_to = expected
                    expected += 1
            except Exception as exc:
                logger.warning(
                    "trade_gap_backfill_failed venue=%s symbol=%s prev=%s cur=%s err=%s",
                    row.venue,
                    row.symbol,
                    prev,
                    row.sequence_id,
                    exc,
                )
            if recovered_to < row.sequence_id - 1:
                self._last_trade_seq[key] = recovered_to
                logger.warning(
                    "trade_gap_unresolved_discarding_current venue=%s symbol=%s recovered_to=%s cur=%s",
                    row.venue,
                    row.symbol,
                    recovered_to,
                    row.sequence_id,
                )
                return False, True

        self._last_trade_seq[key] = row.sequence_id
        return True, False

    def _check_orderbook_gap(self, row: NormalizedOrderBook) -> tuple[bool, bool]:
        if row.update_id is None:
            return True, False
        key = f"{row.venue}:{row.symbol}"
        prev_last = self._last_book_update.get(key)

        # Snapshot rows reset local continuity baseline.
        if row.is_snapshot:
            self._last_book_first[key] = int(row.first_update_id or row.update_id or 0)
            self._last_book_update[key] = int(row.update_id or 0)
            self._book_requires_bridge[key] = False
            return True, False

        # Binance diff-depth continuity: new.U <= prev.u + 1 <= new.u and new.pu == prev.u.
        row_first = int(row.first_update_id or row.update_id or 0)
        row_prev = int(row.prev_update_id or 0)
        row_last = int(row.update_id or 0)
        if row.venue == "binance" and key in self._book_recovery_pending:
            self._book_recovery_pending.discard(key)
            recovered = self._recover_orderbook(row)
            if recovered is not None:
                self.store.append_orderbook(recovered)
                self.stats.orderbooks += 1
                snap_last = int(recovered.update_id or 0)
                self._last_book_first[key] = int(recovered.first_update_id or snap_last)
                self._last_book_update[key] = snap_last
                self._book_requires_bridge[key] = True
                if row_last <= snap_last:
                    return False, False
                if not (row_first <= (snap_last + 1) <= row_last):
                    logger.info(
                        "orderbook_reconnect_bridge_discard venue=%s symbol=%s snap_last=%s cur_first=%s cur_prev=%s cur_last=%s",
                        row.venue,
                        row.symbol,
                        snap_last,
                        row_first,
                        row_prev,
                        row_last,
                    )
                    return False, False
            prev_last = self._last_book_update.get(key)

        if prev_last is None and row.venue == "binance":
            recovered = self._recover_orderbook(row)
            if recovered is None:
                return False, True
            self.store.append_orderbook(recovered)
            self.stats.orderbooks += 1
            prev_last = int(recovered.update_id or 0)
            self._last_book_first[key] = int(recovered.first_update_id or prev_last)
            self._last_book_update[key] = prev_last
            self._book_requires_bridge[key] = True

        if prev_last is not None:
            if row_last <= prev_last:
                logger.debug(
                    "orderbook_out_of_order_discarded venue=%s symbol=%s prev=%s cur_last=%s",
                    row.venue,
                    row.symbol,
                    prev_last,
                    row_last,
                )
                return False, False
            needs_bridge = bool(self._book_requires_bridge.get(key, False))
            contiguous_range = (row_first <= (prev_last + 1) <= row_last)
            if row.venue == "binance":
                contiguous = contiguous_range if needs_bridge else (row_prev == prev_last)
            else:
                # Non-Binance venues often expose different sequence fields that are
                # not strict parent pointers, so keep monotonic update-id continuity.
                contiguous = row_last > prev_last
            if not contiguous:
                self.stats.orderbook_gaps += 1
                logger.warning(
                    "orderbook_gap_detected venue=%s symbol=%s prev=%s cur_first=%s cur_prev=%s cur_last=%s",
                    row.venue,
                    row.symbol,
                    prev_last,
                    row_first,
                    row_prev,
                    row_last,
                )
                if row.venue != "binance":
                    logger.info(
                        "orderbook_soft_resync venue=%s symbol=%s prev=%s cur_last=%s",
                        row.venue,
                        row.symbol,
                        prev_last,
                        row_last,
                    )
                    self._last_book_first[key] = row_first
                    self._last_book_update[key] = row_last
                    self._book_requires_bridge[key] = False
                    return True, True
                recovered = self._recover_orderbook(row)
                if recovered is None:
                    return False, True
                self.store.append_orderbook(recovered)
                self.stats.orderbooks += 1
                snap_last = int(recovered.update_id or 0)
                self._last_book_first[key] = int(recovered.first_update_id or snap_last)
                self._last_book_update[key] = snap_last
                self._book_requires_bridge[key] = True

                if row_last <= snap_last:
                    return False, True
                if not (row_first <= (snap_last + 1) <= row_last):
                    logger.warning(
                        "orderbook_gap_unresolved_discarding_delta venue=%s symbol=%s snap_last=%s cur_first=%s cur_prev=%s cur_last=%s",
                        row.venue,
                        row.symbol,
                        snap_last,
                        row_first,
                        row_prev,
                        row_last,
                    )
                    return False, True

        self._last_book_first[key] = row_first
        self._last_book_update[key] = row_last
        if self._book_requires_bridge.get(key, False):
            self._book_requires_bridge[key] = False
        return True, False

    def _recover_orderbook(self, row: NormalizedOrderBook) -> NormalizedOrderBook | None:
        try:
            return self.adapter.recover_orderbook_snapshot(symbol=row.symbol, receive_ts_ms=row.receive_ts_ms)
        except Exception as exc:
            logger.warning(
                "orderbook_recovery_failed venue=%s symbol=%s err=%s",
                row.venue,
                row.symbol,
                exc,
            )
            return None


async def _run(
    venues: list[str],
    symbols: list[str],
    out_dir: str,
    flush_every: int,
    publish_events: bool,
    redis_url: str,
    strategy_name: str,
    publish_interval_ms: int,
    duration_sec: int,
) -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _stop() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: _stop())

    if duration_sec > 0:
        loop.call_later(float(duration_sec), _stop)

    tasks: list[asyncio.Task] = []
    publisher = MarketEventPublisher(
        redis_url=redis_url,
        strategy_name=strategy_name,
        publish_interval_ms=publish_interval_ms,
    ) if publish_events else None
    for venue in venues:
        adapter = build_adapter(venue)
        store = MicrostructureParquetStore(root_dir=out_dir, flush_every=flush_every)
        ingestor = MultiVenueRealtimeIngestor(
            adapter=adapter,
            symbols=symbols,
            store=store,
            market_publisher=publisher,
        )
        tasks.append(asyncio.create_task(ingestor.run(stop_event)))

    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if publisher is not None:
            publisher.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run realtime multi-venue microstructure capture")
    parser.add_argument("--venues", nargs="+", default=["binance"], help="Supported: binance bybit okx")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT"], help="Symbols, e.g. BTCUSDT ETHUSDT")
    parser.add_argument("--output-dir", default="data/microstructure")
    parser.add_argument("--flush-every", type=int, default=2000)
    parser.add_argument("--publish-events", action="store_true", help="Publish market ticks into events.trading")
    parser.add_argument("--redis-url", default=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    parser.add_argument("--strategy-name", default="default")
    parser.add_argument("--publish-interval-ms", type=int, default=1000)
    parser.add_argument("--duration-sec", type=int, default=0, help="Auto-stop after N seconds (0 means run until interrupted)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    asyncio.run(
        _run(
            venues=[str(v).lower() for v in args.venues],
            symbols=[str(s).upper() for s in args.symbols],
            out_dir=str(args.output_dir),
            flush_every=int(args.flush_every),
            publish_events=bool(args.publish_events),
            redis_url=str(args.redis_url),
            strategy_name=str(args.strategy_name),
            publish_interval_ms=int(args.publish_interval_ms),
            duration_sec=max(0, int(args.duration_sec)),
        )
    )


if __name__ == "__main__":
    main()
