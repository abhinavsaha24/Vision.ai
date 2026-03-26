from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import Any

import pandas as pd

from backend.src.data.venue_adapters import NormalizedOrderBook, NormalizedTrade


class MicrostructureParquetStore:
    """Buffered local parquet sink for trades and orderbook snapshots."""

    def __init__(self, root_dir: str = "data/microstructure", flush_every: int = 2000):
        self.root_dir = Path(root_dir)
        self.flush_every = max(100, int(flush_every))
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._trade_buffer: list[dict[str, Any]] = []
        self._book_buffer: list[dict[str, Any]] = []
        self._lock = Lock()
        self._checkpoint_file = self.root_dir / "_capture_checkpoint.json"
        self._checkpoint = self._load_checkpoint()

    def _load_checkpoint(self) -> dict[str, dict[str, int]]:
        if not self._checkpoint_file.exists():
            return {"trades": {}, "orderbook": {}}
        try:
            payload = json.loads(self._checkpoint_file.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return {"trades": {}, "orderbook": {}}
            trades = payload.get("trades", {}) if isinstance(payload.get("trades", {}), dict) else {}
            books = payload.get("orderbook", {}) if isinstance(payload.get("orderbook", {}), dict) else {}
            return {"trades": {str(k): int(v) for k, v in trades.items()}, "orderbook": {str(k): int(v) for k, v in books.items()}}
        except Exception:
            return {"trades": {}, "orderbook": {}}

    def _save_checkpoint_locked(self) -> None:
        payload = {
            "trades": self._checkpoint.get("trades", {}),
            "orderbook": self._checkpoint.get("orderbook", {}),
            "updated_at_ms": int(time.time() * 1000),
        }
        tmp_path = self._checkpoint_file.with_suffix(f"{self._checkpoint_file.suffix}.tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, indent=2))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, self._checkpoint_file)

    @staticmethod
    def _key(venue: str, symbol: str) -> str:
        return f"{str(venue).lower()}:{str(symbol).upper()}"

    def last_trade_timestamp_ms(self, venue: str, symbol: str) -> int:
        key = self._key(venue, symbol)
        with self._lock:
            return int(self._checkpoint.get("trades", {}).get(key, 0) or 0)

    def last_orderbook_timestamp_ms(self, venue: str, symbol: str) -> int:
        key = self._key(venue, symbol)
        with self._lock:
            return int(self._checkpoint.get("orderbook", {}).get(key, 0) or 0)

    def append_trade(self, row: NormalizedTrade) -> None:
        with self._lock:
            key = self._key(row.venue, row.symbol)
            last_ts = int(self._checkpoint.get("trades", {}).get(key, 0) or 0)
            if int(row.exchange_ts_ms) <= last_ts:
                return
            self._trade_buffer.append(
                {
                    "venue": row.venue,
                    "symbol": row.symbol,
                    "exchange_ts_ms": int(row.exchange_ts_ms),
                    "timestamp": pd.to_datetime(int(row.exchange_ts_ms), unit="ms", utc=True).isoformat(),
                    "receive_ts_ms": int(row.receive_ts_ms),
                    "price": float(row.price),
                    "quantity": float(row.quantity),
                    "side": row.side,
                    "trade_id": int(row.sequence_id) if row.sequence_id is not None else None,
                    "sequence_id": int(row.sequence_id) if row.sequence_id is not None else None,
                }
            )
            self._checkpoint.setdefault("trades", {})[key] = int(row.exchange_ts_ms)
            if len(self._trade_buffer) >= self.flush_every:
                self._flush_trades_locked()

    def append_orderbook(self, row: NormalizedOrderBook) -> None:
        with self._lock:
            key = self._key(row.venue, row.symbol)
            last_ts = int(self._checkpoint.get("orderbook", {}).get(key, 0) or 0)
            if int(row.exchange_ts_ms) <= last_ts:
                return
            mid_price = ((float(row.best_bid) + float(row.best_ask)) / 2.0) if float(row.best_bid) > 0 and float(row.best_ask) > 0 else 0.0
            spread = max(0.0, float(row.best_ask) - float(row.best_bid)) if float(row.best_bid) > 0 and float(row.best_ask) > 0 else 0.0
            spread_bps = (spread / mid_price * 10000.0) if mid_price > 0 else 0.0
            bid_depth_top_n = float(sum(float(q) for _, q in row.bids[:20]))
            ask_depth_top_n = float(sum(float(q) for _, q in row.asks[:20]))
            total_depth = bid_depth_top_n + ask_depth_top_n
            imbalance = ((bid_depth_top_n - ask_depth_top_n) / total_depth) if total_depth > 0 else 0.0
            self._book_buffer.append(
                {
                    "venue": row.venue,
                    "symbol": row.symbol,
                    "exchange_ts_ms": int(row.exchange_ts_ms),
                    "timestamp": pd.to_datetime(int(row.exchange_ts_ms), unit="ms", utc=True).isoformat(),
                    "receive_ts_ms": int(row.receive_ts_ms),
                    "best_bid": float(row.best_bid),
                    "best_ask": float(row.best_ask),
                    "spread": float(spread),
                    "spread_bps": float(spread_bps),
                    "mid_price": float(mid_price),
                    "bid_depth_top_n": float(bid_depth_top_n),
                    "ask_depth_top_n": float(ask_depth_top_n),
                    "total_depth_top_n": float(total_depth),
                    "depth_top_n": float(total_depth),
                    "orderbook_imbalance": float(imbalance),
                    "imbalance": float(imbalance),
                    "depth_levels": int(min(len(row.bids), len(row.asks))),
                    "bid_levels": row.bids,
                    "ask_levels": row.asks,
                    "update_id": int(row.update_id) if row.update_id is not None else None,
                    "first_update_id": int(row.first_update_id) if row.first_update_id is not None else None,
                    "prev_update_id": int(row.prev_update_id) if row.prev_update_id is not None else None,
                    "is_snapshot": bool(row.is_snapshot),
                    "book_mode": str(row.book_mode),
                }
            )
            self._checkpoint.setdefault("orderbook", {})[key] = int(row.exchange_ts_ms)
            if len(self._book_buffer) >= self.flush_every:
                self._flush_books_locked()

    def flush(self) -> None:
        with self._lock:
            self._flush_trades_locked()
            self._flush_books_locked()
            self._save_checkpoint_locked()

    def _flush_trades_locked(self) -> None:
        if not self._trade_buffer:
            return
        data = list(self._trade_buffer)
        df = pd.DataFrame(data)
        self._write_partitioned(df, dataset="trades")
        self._trade_buffer.clear()

    def _flush_books_locked(self) -> None:
        if not self._book_buffer:
            return
        data = list(self._book_buffer)
        df = pd.DataFrame(data)
        self._write_partitioned(df, dataset="orderbook")
        self._book_buffer.clear()

    def _write_partitioned(self, df: pd.DataFrame, dataset: str) -> None:
        if df.empty:
            return

        ts = pd.to_datetime(df["exchange_ts_ms"], unit="ms", utc=True, errors="coerce")
        df = df.assign(
            date=ts.dt.strftime("%Y-%m-%d").fillna("unknown"),
            hour=ts.dt.strftime("%H").fillna("unknown"),
        )

        for (venue, symbol, day, hour), part in df.groupby(["venue", "symbol", "date", "hour"], dropna=False):
            out_dir = self.root_dir / dataset / f"venue={venue}" / f"symbol={symbol}" / f"date={day}" / f"hour={hour}"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / f"chunk_{int(time.time() * 1000)}_{uuid.uuid4().hex}.parquet"
            part = part.sort_values(["exchange_ts_ms", "receive_ts_ms"])
            part.to_parquet(out_file, index=False)
