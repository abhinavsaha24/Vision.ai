from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import websockets

from backend.src.platform.live.types import DepthTop, TradeTick

logger = logging.getLogger(__name__)


class BinanceWebSocketIngestor:
    """Low-latency Binance ingestion for aggTrade and depth using dedicated sockets."""

    def __init__(self, symbol: str, use_depth_stream: bool = True):
        self.symbol = symbol.upper()
        self._stream_symbol = self.symbol.lower()
        self.use_depth_stream = use_depth_stream
        self._running = False

    def _stream_urls(self) -> list[tuple[str, str]]:
        urls: list[tuple[str, str]] = [
            (f"wss://stream.binance.com:9443/ws/{self._stream_symbol}@aggTrade", "aggTrade"),
        ]
        if self.use_depth_stream:
            urls.append((f"wss://stream.binance.com:9443/ws/{self._stream_symbol}@depth20@1000ms", "depth"))
        return urls

    async def run(
        self,
        trade_queue: asyncio.Queue[TradeTick],
        depth_queue: asyncio.Queue[DepthTop],
        stop_event: asyncio.Event,
    ) -> None:
        self._running = True
        tasks = [
            asyncio.create_task(self._run_stream(url, stream, trade_queue, depth_queue, stop_event))
            for url, stream in self._stream_urls()
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_stream(
        self,
        url: str,
        stream: str,
        trade_queue: asyncio.Queue[TradeTick],
        depth_queue: asyncio.Queue[DepthTop],
        stop_event: asyncio.Event,
    ) -> None:
        backoff = 1.0
        while not stop_event.is_set() and self._running:
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_queue=4096,
                ) as ws:
                    logger.info("live_ingestion_connected symbol=%s stream=%s", self.symbol, stream)
                    backoff = 1.0
                    async for raw in ws:
                        if stop_event.is_set() or not self._running:
                            break
                        await self._handle_raw(raw, stream, trade_queue, depth_queue)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - network errors are environment dependent.
                logger.warning("live_ingestion_error symbol=%s stream=%s err=%s", self.symbol, stream, exc)
                await asyncio.sleep(backoff)
                backoff = min(60.0, backoff * 2.0)

    def stop(self) -> None:
        self._running = False

    async def _handle_raw(
        self,
        raw: str | bytes,
        stream_hint: str,
        trade_queue: asyncio.Queue[TradeTick],
        depth_queue: asyncio.Queue[DepthTop],
    ) -> None:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("live_ingestion_message_parse_failed symbol=%s err=%s raw=%s", self.symbol, exc, raw)
            return
        stream = str(payload.get("e", stream_hint))
        data = payload
        receive_ts_ms = int(time.time() * 1000)

        if stream in {"aggTrade", "trade"}:
            trade = self._parse_trade(data, receive_ts_ms)
            if trade is not None:
                await self._queue_put_latest(trade_queue, trade)
            return

        if stream in {"depthUpdate", "depth"}:
            depth = self._parse_depth(data, receive_ts_ms)
            if depth is not None:
                await self._queue_put_latest(depth_queue, depth)

    def _parse_trade(self, data: dict[str, Any], receive_ts_ms: int) -> TradeTick | None:
        try:
            return TradeTick(
                symbol=self.symbol,
                price=float(data.get("p", 0.0) or 0.0),
                quantity=float(data.get("q", 0.0) or 0.0),
                exchange_ts_ms=int(data.get("T", 0) or 0),
                receive_ts_ms=receive_ts_ms,
                is_buyer_maker=bool(data.get("m", False)),
            )
        except Exception:
            return None

    def _parse_depth(self, data: dict[str, Any], receive_ts_ms: int) -> DepthTop | None:
        try:
            bids = data.get("b", data.get("bids", []))
            asks = data.get("a", data.get("asks", []))
            if not bids or not asks:
                return None
            bid_levels = [(float(p), float(q)) for p, q in bids[:20]]
            ask_levels = [(float(p), float(q)) for p, q in asks[:20]]
            bid0 = bid_levels[0]
            ask0 = ask_levels[0]
            return DepthTop(
                symbol=self.symbol,
                best_bid=float(bid0[0]),
                best_ask=float(ask0[0]),
                bid_qty=float(bid0[1]),
                ask_qty=float(ask0[1]),
                bids=bid_levels,
                asks=ask_levels,
                exchange_ts_ms=int(data.get("E", 0) or 0),
                receive_ts_ms=receive_ts_ms,
            )
        except Exception:
            return None

    @staticmethod
    async def _queue_put_latest(queue: asyncio.Queue[Any], item: Any) -> None:
        # Intentionally drop oldest item on overflow; do not mutate unfinished-task counters here.
        if queue.full():
            try:
                queue.get_nowait()
                try:
                    queue.task_done()
                except Exception:
                    pass
            except Exception:
                pass
        await queue.put(item)
