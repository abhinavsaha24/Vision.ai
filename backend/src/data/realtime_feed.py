"""Realtime market data feed with Binance WebSocket primary and REST fallback."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

import ccxt
import numpy as np
import websockets

from backend.src.core.cache import RedisCache

logger = logging.getLogger(__name__)


class RealtimeMarketFeed:
    """Maintains per-symbol realtime ticker, trade, and L2 depth state."""

    def __init__(
        self,
        cache: Optional[RedisCache] = None,
        stale_after_seconds: float = 15.0,
        ws_enabled: bool = True,
        ws_open_timeout_seconds: float = 12.0,
        ws_max_consecutive_failures: int = 5,
        ws_cooldown_seconds: float = 90.0,
        rest_poll_seconds: float = 6.0,
    ):
        self.cache = cache
        self.stale_after_seconds = stale_after_seconds
        self.ws_enabled = bool(ws_enabled)
        self.ws_open_timeout_seconds = float(ws_open_timeout_seconds)
        self.ws_max_consecutive_failures = max(1, int(ws_max_consecutive_failures))
        self.ws_cooldown_seconds = max(5.0, float(ws_cooldown_seconds))
        self.rest_poll_seconds = max(1.0, float(rest_poll_seconds))
        self._running = False
        self._tasks: Dict[str, asyncio.Task] = {}
        self._state: Dict[str, Dict[str, Any]] = defaultdict(dict)
        self._recent_trades: Dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
        self._recent_mid_prices: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=200)
        )
        self._exchange = ccxt.binance(
            {"enableRateLimit": True, "options": {"defaultType": "spot"}}
        )

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        clean = symbol.upper().replace("/", "").replace("-", "")
        return clean or "BTCUSDT"

    @staticmethod
    def exchange_symbol(symbol: str) -> str:
        clean = RealtimeMarketFeed.normalize_symbol(symbol)
        if clean.endswith("USDT"):
            return f"{clean[:-4]}/USDT"
        return clean

    async def start(self, symbols: Optional[Iterable[str]] = None) -> None:
        self._running = True
        for symbol in symbols or ["BTCUSDT"]:
            await self.ensure_symbol(symbol)

    async def stop(self) -> None:
        self._running = False
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def ensure_symbol(self, symbol: str) -> None:
        normalized = self.normalize_symbol(symbol)
        if normalized in self._tasks and not self._tasks[normalized].done():
            return
        self._tasks[normalized] = asyncio.create_task(self._run_symbol(normalized))

    def get_snapshot(self, symbol: str) -> Dict[str, Any]:
        normalized = self.normalize_symbol(symbol)
        snapshot = dict(self._state.get(normalized, {}))
        if not snapshot or self.is_stale(normalized):
            snapshot = self._refresh_from_rest(normalized)
        if not snapshot:
            return self._empty_snapshot(normalized)
        snapshot.setdefault("symbol", normalized)
        snapshot["stale"] = self.is_stale(normalized)
        snapshot["age_seconds"] = round(
            max(0.0, time.time() - snapshot.get("updated_at_ts", 0.0)), 3
        )
        return snapshot

    def is_stale(self, symbol: str) -> bool:
        normalized = self.normalize_symbol(symbol)
        updated = self._state.get(normalized, {}).get("updated_at_ts", 0.0)
        if updated <= 0:
            return True
        return (time.time() - updated) > self.stale_after_seconds

    async def _run_symbol(self, symbol: str) -> None:
        await asyncio.to_thread(self._refresh_from_rest, symbol)
        tasks = [asyncio.create_task(self._run_rest_poll(symbol))]

        if self.ws_enabled:
            stream_symbol = symbol.lower()
            streams = [
                (f"wss://stream.binance.com:9443/ws/{stream_symbol}@ticker", "ticker"),
                (f"wss://stream.binance.com:9443/ws/{stream_symbol}@trade", "trade"),
                (f"wss://stream.binance.com:9443/ws/{stream_symbol}@depth20@1000ms", "depth"),
            ]
            tasks.extend(
                [
                    asyncio.create_task(
                        self._run_symbol_stream(symbol, url, stream_name)
                    )
                    for url, stream_name in streams
                ]
            )
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_rest_poll(self, symbol: str) -> None:
        while self._running:
            await asyncio.to_thread(self._refresh_from_rest, symbol)
            await asyncio.sleep(self.rest_poll_seconds)

    async def _run_symbol_stream(self, symbol: str, ws_url: str, stream_name: str) -> None:
        backoff = 1.0
        consecutive_failures = 0
        while self._running:
            try:
                async with websockets.connect(
                    ws_url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    open_timeout=self.ws_open_timeout_seconds,
                ) as socket:
                    logger.info("Realtime feed connected for %s stream=%s", symbol, stream_name)
                    backoff = 1.0
                    consecutive_failures = 0
                    async for raw_message in socket:
                        if not self._running:
                            break
                        self._handle_message(symbol, raw_message, stream_name)
            except Exception as exc:
                consecutive_failures += 1
                logger.warning(
                    "Realtime feed reconnect for %s stream=%s after error: %s",
                    symbol,
                    stream_name,
                    exc,
                )
                self._state.setdefault(symbol, {})["last_error"] = str(exc)

                if consecutive_failures >= self.ws_max_consecutive_failures:
                    logger.info(
                        "Realtime stream cooldown for %s stream=%s after %s failures; sleeping %.1fs",
                        symbol,
                        stream_name,
                        consecutive_failures,
                        self.ws_cooldown_seconds,
                    )
                    await asyncio.sleep(self.ws_cooldown_seconds)
                    consecutive_failures = 0
                    backoff = 1.0
                    continue

                await asyncio.sleep(backoff)
                backoff = min(60.0, backoff * 2.0)

    def _handle_message(self, symbol: str, raw_message: str, stream_hint: str) -> None:
        payload = json.loads(raw_message)
        stream = str(payload.get("e", stream_hint))
        data = payload

        state = self._state.setdefault(symbol, self._empty_snapshot(symbol))
        state["symbol"] = symbol
        state["exchange"] = "binance"
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        state["updated_at_ts"] = time.time()
        state["connection_state"] = "streaming"

        if stream in {"24hrTicker", "ticker"}:
            last_price = float(data.get("c", state.get("last_price", 0.0)) or 0.0)
            state["last_price"] = last_price
            state["best_bid"] = float(
                data.get("b", state.get("best_bid", last_price)) or last_price
            )
            state["best_ask"] = float(
                data.get("a", state.get("best_ask", last_price)) or last_price
            )
            state["bid_volume"] = float(
                data.get("B", state.get("bid_volume", 0.0)) or 0.0
            )
            state["ask_volume"] = float(
                data.get("A", state.get("ask_volume", 0.0)) or 0.0
            )
            state["volume_24h"] = float(
                data.get("v", state.get("volume_24h", 0.0)) or 0.0
            )
        elif stream in {"trade", "aggTrade"}:
            trade = {
                "price": float(data.get("p", 0.0) or 0.0),
                "quantity": float(data.get("q", 0.0) or 0.0),
                "side": "sell" if data.get("m") else "buy",
                "timestamp": datetime.fromtimestamp(
                    (data.get("T", 0) or 0) / 1000, tz=timezone.utc
                ).isoformat(),
            }
            self._recent_trades[symbol].append(trade)
            state["last_trade"] = trade
        elif stream in {"depthUpdate", "depth"}:
            bids = [
                [float(price), float(size)] for price, size in data.get("b", data.get("bids", []))[:20]
            ]
            asks = [
                [float(price), float(size)] for price, size in data.get("a", data.get("asks", []))[:20]
            ]
            state["bids"] = bids
            state["asks"] = asks
            if bids:
                state["best_bid"] = bids[0][0]
                state["bid_volume"] = bids[0][1]
            if asks:
                state["best_ask"] = asks[0][0]
                state["ask_volume"] = asks[0][1]

        self._enrich_state(state)
        symbol_key = state.get("symbol", symbol)
        self._recent_mid_prices[symbol_key].append(float(state.get("mid_price", 0.0) or 0.0))
        self._publish_snapshot(symbol, state)

    def _enrich_state(self, state: Dict[str, Any]) -> None:
        best_bid = float(state.get("best_bid", 0.0) or 0.0)
        best_ask = float(state.get("best_ask", 0.0) or 0.0)
        last_price = float(state.get("last_price", 0.0) or 0.0)
        mid_price = (
            ((best_bid + best_ask) / 2.0)
            if best_bid > 0 and best_ask > 0
            else last_price
        )
        spread = max(0.0, best_ask - best_bid) if best_bid > 0 and best_ask > 0 else 0.0
        spread_bps = (spread / mid_price * 10000.0) if mid_price > 0 else 0.0

        bids = state.get("bids", [])[:10]
        asks = state.get("asks", [])[:10]
        bid_depth = sum(level[1] for level in bids)
        ask_depth = sum(level[1] for level in asks)
        total_depth = bid_depth + ask_depth
        imbalance = ((bid_depth - ask_depth) / total_depth) if total_depth > 0 else 0.0

        symbol = state.get("symbol", "")
        recent_trades = list(self._recent_trades.get(symbol, []))
        buy_volume = sum(
            float(t.get("quantity", 0.0) or 0.0)
            for t in recent_trades
            if t.get("side") == "buy"
        )
        sell_volume = sum(
            float(t.get("quantity", 0.0) or 0.0)
            for t in recent_trades
            if t.get("side") == "sell"
        )
        total_flow = buy_volume + sell_volume
        volume_delta = ((buy_volume - sell_volume) / total_flow) if total_flow > 0 else 0.0

        recent_mid_prices = [
            p for p in self._recent_mid_prices.get(symbol, []) if isinstance(p, (int, float)) and p > 0
        ]
        volatility_expansion = 0.0
        if len(recent_mid_prices) >= 40:
            arr = np.array(recent_mid_prices, dtype=float)
            rets = np.diff(arr) / np.maximum(arr[:-1], 1e-8)
            if len(rets) >= 20:
                short_vol = float(np.std(rets[-10:]))
                long_vol = float(np.std(rets[-40:]))
                volatility_expansion = (
                    (short_vol / max(long_vol, 1e-8)) - 1.0
                )

        state["mid_price"] = round(mid_price, 8)
        state["spread"] = round(spread, 8)
        state["spread_bps"] = round(spread_bps, 4)
        state["order_book_imbalance"] = round(imbalance, 6)
        state["volume_delta"] = round(float(volume_delta), 6)
        state["volatility_expansion"] = round(float(volatility_expansion), 6)
        state["recent_trades"] = list(
            self._recent_trades.get(state.get("symbol", ""), [])
        )[-25:]

    def _refresh_from_rest(self, symbol: str) -> Dict[str, Any]:
        try:
            exchange_symbol = self.exchange_symbol(symbol)
            ticker = self._exchange.fetch_ticker(exchange_symbol)
            book = self._exchange.fetch_order_book(exchange_symbol, limit=20)
            state = self._state.setdefault(symbol, self._empty_snapshot(symbol))
            state.update(
                {
                    "symbol": symbol,
                    "exchange": "binance",
                    "last_price": float(ticker.get("last") or 0.0),
                    "best_bid": float(ticker.get("bid") or 0.0),
                    "best_ask": float(ticker.get("ask") or 0.0),
                    "volume_24h": float(ticker.get("baseVolume") or 0.0),
                    "bids": [
                        [float(price), float(size)]
                        for price, size in book.get("bids", [])[:20]
                    ],
                    "asks": [
                        [float(price), float(size)]
                        for price, size in book.get("asks", [])[:20]
                    ],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at_ts": time.time(),
                    "connection_state": "rest-fallback",
                }
            )
            self._enrich_state(state)
            self._publish_snapshot(symbol, state)
            return dict(state)
        except Exception as exc:
            logger.warning("Realtime REST fallback failed for %s: %s", symbol, exc)
            self._state.setdefault(symbol, self._empty_snapshot(symbol))[
                "last_error"
            ] = str(exc)
            return dict(self._state.get(symbol, self._empty_snapshot(symbol)))

    def _publish_snapshot(self, symbol: str, state: Dict[str, Any]) -> None:
        if not self.cache:
            return
        payload = dict(state)
        payload["stale"] = self.is_stale(symbol)
        self.cache.set_json(
            f"market:snapshot:{symbol}",
            payload,
            ttl=max(int(self.stale_after_seconds * 3), 30),
        )
        self.cache.publish("market:snapshots", payload)

    @staticmethod
    def _empty_snapshot(symbol: str) -> Dict[str, Any]:
        return {
            "symbol": symbol,
            "exchange": "binance",
            "last_price": 0.0,
            "mid_price": 0.0,
            "spread": 0.0,
            "spread_bps": 0.0,
            "order_book_imbalance": 0.0,
            "volume_delta": 0.0,
            "volatility_expansion": 0.0,
            "volume_24h": 0.0,
            "bids": [],
            "asks": [],
            "recent_trades": [],
            "connection_state": "initializing",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_at_ts": 0.0,
        }
