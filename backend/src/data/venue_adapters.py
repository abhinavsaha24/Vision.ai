from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(slots=True)
class NormalizedTrade:
    venue: str
    symbol: str
    exchange_ts_ms: int
    receive_ts_ms: int
    price: float
    quantity: float
    side: str
    sequence_id: int | None = None


@dataclass(slots=True)
class NormalizedOrderBook:
    venue: str
    symbol: str
    exchange_ts_ms: int
    receive_ts_ms: int
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]
    best_bid: float
    best_ask: float
    update_id: int | None = None
    first_update_id: int | None = None
    prev_update_id: int | None = None
    is_snapshot: bool = False
    book_mode: str = "snapshot"


class VenueAdapter:
    name: str = ""

    def build_stream_urls(self, symbols: list[str]) -> list[str]:
        raise NotImplementedError

    def build_subscribe_payload(self, symbols: list[str]) -> dict[str, Any] | None:
        return None

    def parse_message(self, raw: str, receive_ts_ms: int) -> tuple[list[NormalizedTrade], list[NormalizedOrderBook]]:
        raise NotImplementedError

    def recover_orderbook_snapshot(self, symbol: str, receive_ts_ms: int) -> NormalizedOrderBook | None:
        return None

    def backfill_trade_gap(
        self,
        symbol: str,
        from_sequence_id: int,
        to_sequence_id: int,
        receive_ts_ms: int,
    ) -> list[NormalizedTrade]:
        return []

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        return str(symbol).upper().replace("/", "").replace("-", "")


class BinanceAdapter(VenueAdapter):
    name = "binance"

    def __init__(self):
        self._session = requests.Session()

    def _request_json_with_backoff(
        self,
        url: str,
        params: dict[str, Any],
        max_attempts: int = 6,
        timeout: float = 6.0,
    ) -> Any:
        backoff = 0.5
        last_err: Exception | None = None
        for _ in range(max_attempts):
            try:
                response = self._session.get(url, params=params, timeout=timeout)
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    sleep_s = float(retry_after) if retry_after else backoff
                    time.sleep(max(0.1, sleep_s))
                    backoff = min(15.0, backoff * 2.0)
                    continue
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                last_err = exc
                time.sleep(backoff)
                backoff = min(15.0, backoff * 2.0)
        if last_err is not None:
            raise last_err
        raise RuntimeError("binance_request_failed")

    def build_stream_urls(self, symbols: list[str]) -> list[str]:
        urls: list[str] = []
        for symbol in symbols:
            s = self.normalize_symbol(symbol).lower()
            # Use dedicated per-stream sockets to reduce multiplexing pressure.
            urls.append(f"wss://fstream.binance.com/ws/{s}@aggTrade")
            # Use high-frequency diff-depth for low-latency orderbook capture.
            urls.append(f"wss://fstream.binance.com/ws/{s}@depth@100ms")
        return urls

    def parse_message(self, raw: str, receive_ts_ms: int) -> tuple[list[NormalizedTrade], list[NormalizedOrderBook]]:
        payload = json.loads(raw)
        if isinstance(payload, dict) and "stream" in payload and "data" in payload:
            stream = str(payload.get("stream", ""))
            data = payload.get("data", {}) or {}
        else:
            event = str(payload.get("e", ""))
            stream = event
            data = payload

        trades: list[NormalizedTrade] = []
        books: list[NormalizedOrderBook] = []

        if "@aggTrade" in stream or stream == "aggTrade":
            symbol = self.normalize_symbol(str(data.get("s", "")))
            if symbol:
                trades.append(
                    NormalizedTrade(
                        venue=self.name,
                        symbol=symbol,
                        exchange_ts_ms=int(data.get("T", 0) or 0),
                        receive_ts_ms=receive_ts_ms,
                        price=float(data.get("p", 0.0) or 0.0),
                        quantity=float(data.get("q", 0.0) or 0.0),
                        side="sell" if bool(data.get("m", False)) else "buy",
                        sequence_id=int(data.get("a", 0) or 0),
                    )
                )

        if "@depth" in stream or stream in {"depthUpdate", "depth"}:
            symbol = self.normalize_symbol(str(data.get("s", "")))
            bids_raw = data.get("b", data.get("bids", [])) or []
            asks_raw = data.get("a", data.get("asks", [])) or []
            bids = [(float(p), float(q)) for p, q in bids_raw[:20]]
            asks = [(float(p), float(q)) for p, q in asks_raw[:20]]
            if symbol:
                best_bid = float(bids[0][0]) if bids else 0.0
                best_ask = float(asks[0][0]) if asks else 0.0
                books.append(
                    NormalizedOrderBook(
                        venue=self.name,
                        symbol=symbol,
                        exchange_ts_ms=int(data.get("E", 0) or 0),
                        receive_ts_ms=receive_ts_ms,
                        bids=bids,
                        asks=asks,
                        best_bid=best_bid,
                        best_ask=best_ask,
                        update_id=int(data.get("u", 0) or 0),
                        first_update_id=int(data.get("U", 0) or 0),
                        prev_update_id=int(data.get("pu", 0) or 0),
                        is_snapshot=False,
                        book_mode="diff",
                    )
                )

        return trades, books

    def backfill_trade_gap(
        self,
        symbol: str,
        from_sequence_id: int,
        to_sequence_id: int,
        receive_ts_ms: int,
    ) -> list[NormalizedTrade]:
        if to_sequence_id <= from_sequence_id:
            return []

        recovered: list[NormalizedTrade] = []
        next_id = max(0, int(from_sequence_id))
        final_id = int(to_sequence_id)
        while next_id < final_id:
            params = {
                "symbol": self.normalize_symbol(symbol),
                "fromId": next_id,
                "limit": min(1000, max(1, final_id - next_id)),
            }
            payload = self._request_json_with_backoff("https://fapi.binance.com/fapi/v1/aggTrades", params=params)
            if not isinstance(payload, list) or not payload:
                break

            max_seen = next_id
            for row in payload:
                seq = int(row.get("a", 0) or 0)
                if seq <= from_sequence_id or seq >= to_sequence_id:
                    continue
                recovered.append(
                    NormalizedTrade(
                        venue=self.name,
                        symbol=self.normalize_symbol(str(row.get("s", symbol))),
                        exchange_ts_ms=int(row.get("T", 0) or 0),
                        receive_ts_ms=receive_ts_ms,
                        price=float(row.get("p", 0.0) or 0.0),
                        quantity=float(row.get("q", 0.0) or 0.0),
                        side="sell" if bool(row.get("m", False)) else "buy",
                        sequence_id=seq,
                    )
                )
                if seq > max_seen:
                    max_seen = seq

            if max_seen <= next_id:
                break
            next_id = max_seen + 1

        recovered.sort(key=lambda x: int(x.sequence_id or 0))
        return recovered

    def recover_orderbook_snapshot(self, symbol: str, receive_ts_ms: int) -> NormalizedOrderBook | None:
        params = {"symbol": self.normalize_symbol(symbol), "limit": 1000}
        payload = self._request_json_with_backoff("https://fapi.binance.com/fapi/v1/depth", params=params)
        bids_raw = payload.get("bids", []) or []
        asks_raw = payload.get("asks", []) or []
        bids = [(float(p), float(q)) for p, q in bids_raw[:50]]
        asks = [(float(p), float(q)) for p, q in asks_raw[:50]]
        if not bids or not asks:
            return None
        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        update_id = int(payload.get("lastUpdateId", 0) or 0)
        return NormalizedOrderBook(
            venue=self.name,
            symbol=self.normalize_symbol(symbol),
            exchange_ts_ms=int(receive_ts_ms),
            receive_ts_ms=int(receive_ts_ms),
            bids=bids,
            asks=asks,
            best_bid=best_bid,
            best_ask=best_ask,
            update_id=update_id,
            first_update_id=update_id,
            prev_update_id=update_id,
            is_snapshot=True,
            book_mode="snapshot",
        )


class BybitAdapter(VenueAdapter):
    name = "bybit"

    def build_stream_urls(self, symbols: list[str]) -> list[str]:
        return ["wss://stream.bybit.com/v5/public/linear"] if symbols else []

    def build_subscribe_payload(self, symbols: list[str]) -> dict[str, Any] | None:
        if not symbols:
            return None
        args: list[str] = []
        for symbol in symbols:
            s = self.normalize_symbol(symbol)
            args.append(f"publicTrade.{s}")
            args.append(f"orderbook.50.{s}")
        return {"op": "subscribe", "args": args}

    def parse_message(self, raw: str, receive_ts_ms: int) -> tuple[list[NormalizedTrade], list[NormalizedOrderBook]]:
        payload = json.loads(raw)
        topic = str(payload.get("topic", ""))
        rows = payload.get("data", []) or []
        if isinstance(rows, dict):
            rows = [rows]

        trades: list[NormalizedTrade] = []
        books: list[NormalizedOrderBook] = []

        if topic.startswith("publicTrade."):
            for row in rows:
                symbol = self.normalize_symbol(str(row.get("s", "")))
                if not symbol:
                    continue
                trades.append(
                    NormalizedTrade(
                        venue=self.name,
                        symbol=symbol,
                        exchange_ts_ms=int(row.get("T", 0) or 0),
                        receive_ts_ms=receive_ts_ms,
                        price=float(row.get("p", 0.0) or 0.0),
                        quantity=float(row.get("v", 0.0) or 0.0),
                        side="buy" if str(row.get("S", "")).lower() == "buy" else "sell",
                        sequence_id=int(row.get("i", 0) or 0),
                    )
                )

        if topic.startswith("orderbook.") and rows:
            row = rows[0]
            symbol = self.normalize_symbol(str(row.get("s", "")))
            bids = [(float(p), float(q)) for p, q in (row.get("b", []) or [])[:20]]
            asks = [(float(p), float(q)) for p, q in (row.get("a", []) or [])[:20]]
            if symbol and bids and asks:
                books.append(
                    NormalizedOrderBook(
                        venue=self.name,
                        symbol=symbol,
                        exchange_ts_ms=int(row.get("ts", payload.get("ts", 0)) or 0),
                        receive_ts_ms=receive_ts_ms,
                        bids=bids,
                        asks=asks,
                        best_bid=float(bids[0][0]),
                        best_ask=float(asks[0][0]),
                        update_id=int(row.get("u", 0) or 0),
                        first_update_id=int(row.get("u", 0) or 0),
                        prev_update_id=int(row.get("seq", row.get("u", 0)) or 0),
                        is_snapshot=(str(row.get("type", "")).lower() == "snapshot"),
                        book_mode="diff",
                    )
                )

        return trades, books


class OkxAdapter(VenueAdapter):
    name = "okx"

    def build_stream_urls(self, symbols: list[str]) -> list[str]:
        return ["wss://ws.okx.com:8443/ws/v5/public"] if symbols else []

    def build_subscribe_payload(self, symbols: list[str]) -> dict[str, Any] | None:
        if not symbols:
            return None
        args: list[dict[str, str]] = []
        for symbol in symbols:
            s = self.normalize_symbol(symbol)
            base = s[:-4] if s.endswith("USDT") and len(s) > 4 else s
            inst = f"{base}-USDT-SWAP" if s.endswith("USDT") and len(s) > 4 else f"{s}-SWAP"
            args.append({"channel": "trades", "instId": inst})
            args.append({"channel": "books50-l2-tbt", "instId": inst})
        return {"op": "subscribe", "args": args}

    def parse_message(self, raw: str, receive_ts_ms: int) -> tuple[list[NormalizedTrade], list[NormalizedOrderBook]]:
        payload = json.loads(raw)
        arg = payload.get("arg", {}) or {}
        channel = str(arg.get("channel", ""))
        rows = payload.get("data", []) or []

        trades: list[NormalizedTrade] = []
        books: list[NormalizedOrderBook] = []

        if channel == "trades":
            for row in rows:
                inst = str(row.get("instId", ""))
                symbol = self.normalize_symbol(inst.replace("-USDT-SWAP", "USDT").replace("-", ""))
                if not symbol:
                    continue
                side = str(row.get("side", "")).lower()
                trades.append(
                    NormalizedTrade(
                        venue=self.name,
                        symbol=symbol,
                        exchange_ts_ms=int(row.get("ts", 0) or 0),
                        receive_ts_ms=receive_ts_ms,
                        price=float(row.get("px", 0.0) or 0.0),
                        quantity=float(row.get("sz", 0.0) or 0.0),
                        side="buy" if side == "buy" else "sell",
                        sequence_id=None,
                    )
                )

        if channel.startswith("books"):
            for row in rows:
                inst = str(row.get("instId", ""))
                symbol = self.normalize_symbol(inst.replace("-USDT-SWAP", "USDT").replace("-", ""))
                bids = [(float(p), float(q)) for p, q, *_ in (row.get("bids", []) or [])[:20]]
                asks = [(float(p), float(q)) for p, q, *_ in (row.get("asks", []) or [])[:20]]
                if symbol and bids and asks:
                    books.append(
                        NormalizedOrderBook(
                            venue=self.name,
                            symbol=symbol,
                            exchange_ts_ms=int(row.get("ts", 0) or 0),
                            receive_ts_ms=receive_ts_ms,
                            bids=bids,
                            asks=asks,
                            best_bid=float(bids[0][0]),
                            best_ask=float(asks[0][0]),
                            update_id=None,
                            first_update_id=None,
                            prev_update_id=None,
                            is_snapshot=False,
                            book_mode="diff",
                        )
                    )

        return trades, books


def build_adapter(venue: str) -> VenueAdapter:
    v = str(venue).strip().lower()
    if v == "binance":
        return BinanceAdapter()
    if v == "bybit":
        return BybitAdapter()
    if v == "okx":
        return OkxAdapter()
    raise ValueError(f"unsupported_venue:{venue}")
