from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


@dataclass
class BinanceFlowConfig:
    base_url: str = "https://fapi.binance.com"
    timeout_seconds: float = 8.0
    max_retries: int = 3
    retry_backoff_seconds: float = 0.8
    cache_ttl_seconds: float = 20.0


class BinanceFlowClient:
    """Binance futures flow client with retries, timeout handling, and lightweight caching."""

    def __init__(self, config: BinanceFlowConfig | None = None):
        self.config = config or BinanceFlowConfig()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "vision-ai/binance-flow"})
        self._cache: dict[str, _CacheEntry] = {}
        self._cache_lock = Lock()

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        s = str(symbol).upper().replace("/", "").replace("-", "")
        if s.endswith("USD") and not s.endswith("USDT"):
            s = s[:-3] + "USDT"
        return s

    def _cache_get(self, key: str) -> Any | None:
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if entry.expires_at < time.time():
                self._cache.pop(key, None)
                return None
            return entry.value

    def _cache_set(self, key: str, value: Any, ttl: float | None = None) -> None:
        with self._cache_lock:
            self._cache[key] = _CacheEntry(
                value=value,
                expires_at=time.time() + float(ttl or self.config.cache_ttl_seconds),
            )

    def _request_json(self, endpoint: str, params: dict[str, Any], cache_key: str | None = None) -> Any:
        if cache_key:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached

        url = f"{self.config.base_url}{endpoint}"
        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.config.timeout_seconds)
                response.raise_for_status()
                payload = response.json()
                if cache_key:
                    self._cache_set(cache_key, payload)
                return payload
            except Exception as exc:
                last_error = exc
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                if isinstance(status_code, int) and 400 <= status_code < 500:
                    break
                if attempt >= self.config.max_retries:
                    break
                time.sleep(self.config.retry_backoff_seconds * attempt)

        raise RuntimeError(f"binance_flow_request_failed endpoint={endpoint} err={last_error}")

    def get_open_interest(self, symbol: str) -> float:
        sym = self.normalize_symbol(symbol)
        data = self._request_json(
            "/fapi/v1/openInterest",
            {"symbol": sym},
            cache_key=f"oi:{sym}",
        )
        return float(data.get("openInterest", 0.0) or 0.0)

    def get_funding_rates(self, symbol: str, limit: int = 200) -> pd.DataFrame:
        sym = self.normalize_symbol(symbol)
        data = self._request_json(
            "/fapi/v1/fundingRate",
            {"symbol": sym, "limit": int(limit)},
            cache_key=f"funding:{sym}:{int(limit)}",
        )
        if not isinstance(data, list) or not data:
            return pd.DataFrame(columns=["funding_rate"])
        frame = pd.DataFrame(data)
        if frame.empty or "fundingTime" not in frame.columns or "fundingRate" not in frame.columns:
            return pd.DataFrame(columns=["funding_rate"])
        frame["ts"] = pd.to_datetime(frame["fundingTime"], unit="ms", utc=True)
        out = pd.DataFrame(index=frame["ts"])
        out["funding_rate"] = pd.to_numeric(frame["fundingRate"], errors="coerce").fillna(0.0)
        return out.sort_index()

    def get_force_orders(
        self,
        symbol: str,
        limit: int = 200,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> pd.DataFrame:
        sym = self.normalize_symbol(symbol)
        params: dict[str, Any] = {"symbol": sym, "limit": int(limit)}
        if start_time_ms is not None:
            params["startTime"] = int(start_time_ms)
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)

        data = self._request_json(
            "/fapi/v1/allForceOrders",
            params,
            cache_key=f"force:{sym}:{int(limit)}:{start_time_ms}:{end_time_ms}",
        )
        if not isinstance(data, list) or not data:
            return pd.DataFrame(columns=["liquidation_long_usd", "liquidation_short_usd"])

        frame = pd.DataFrame(data)
        time_source = "time" if "time" in frame.columns else ("T" if "T" in frame.columns else None)
        if time_source is None:
            frame["ts"] = pd.NaT
        else:
            frame["ts"] = pd.to_datetime(frame[time_source], unit="ms", utc=True, errors="coerce")
        qty_series = frame["origQty"] if "origQty" in frame.columns else pd.Series(0.0, index=frame.index)
        price_series = frame["price"] if "price" in frame.columns else pd.Series(0.0, index=frame.index)
        side_series = frame["side"] if "side" in frame.columns else pd.Series("", index=frame.index)

        frame["qty"] = pd.to_numeric(qty_series, errors="coerce").fillna(0.0)
        frame["price"] = pd.to_numeric(price_series, errors="coerce").fillna(0.0)
        frame["usd"] = frame["qty"] * frame["price"]

        # In force orders, SELL generally maps to long liquidation; BUY maps to short liquidation.
        frame["liquidation_long_usd"] = frame["usd"].where(side_series == "SELL", 0.0)
        frame["liquidation_short_usd"] = frame["usd"].where(side_series == "BUY", 0.0)

        out = frame.set_index("ts")[["liquidation_long_usd", "liquidation_short_usd"]]
        out = out.groupby(out.index).sum().sort_index()
        return out

    def get_flow_snapshot(self, symbol: str) -> dict[str, float]:
        sym = self.normalize_symbol(symbol)
        snapshot: dict[str, float] = {
            "open_interest": 0.0,
            "funding_rate": 0.0,
            "liquidation_long_usd": 0.0,
            "liquidation_short_usd": 0.0,
        }

        try:
            snapshot["open_interest"] = self.get_open_interest(sym)
        except Exception as exc:
            logger.warning("flow_open_interest_fetch_failed symbol=%s err=%s", sym, exc)

        try:
            f = self.get_funding_rates(sym, limit=8)
            if not f.empty:
                snapshot["funding_rate"] = float(f["funding_rate"].iloc[-1])
        except Exception as exc:
            logger.warning("flow_funding_fetch_failed symbol=%s err=%s", sym, exc)

        try:
            end_ms = int(time.time() * 1000)
            start_ms = end_ms - (6 * 60 * 60 * 1000)
            force = self.get_force_orders(sym, limit=200, start_time_ms=start_ms, end_time_ms=end_ms)
            if not force.empty:
                snapshot["liquidation_long_usd"] = float(force["liquidation_long_usd"].sum())
                snapshot["liquidation_short_usd"] = float(force["liquidation_short_usd"].sum())
        except Exception as exc:
            logger.warning("flow_force_orders_fetch_failed symbol=%s err=%s", sym, exc)

        return snapshot

    def build_historical_flow_frame(
        self,
        index: pd.DatetimeIndex,
        symbol: str,
        interval: str = "1h",
    ) -> pd.DataFrame:
        """
        Build a historical flow frame aligned to target index.

        If API retrieval is sparse/unavailable, falls back to POSITIONING_DATA_CSV.
        """
        idx = pd.DatetimeIndex(pd.to_datetime(index, utc=True))
        out = pd.DataFrame(index=idx)

        csv_path = os.getenv("POSITIONING_DATA_CSV", "").strip()
        if csv_path:
            try:
                csv_df = pd.read_csv(csv_path)
                if "ts" in csv_df.columns:
                    csv_df["ts"] = pd.to_datetime(csv_df["ts"], utc=True)
                    csv_df = csv_df.set_index("ts").sort_index()
                    out = out.join(csv_df, how="left")
            except Exception as exc:
                logger.warning("positioning_csv_load_failed err=%s", exc)

        # Funding history is naturally historical.
        try:
            funding = self.get_funding_rates(symbol, limit=1000)
            if not funding.empty:
                out = out.join(funding, how="left")
        except Exception as exc:
            logger.warning("historical_funding_fetch_failed symbol=%s err=%s", symbol, exc)

        # Force orders over the index span.
        try:
            if len(idx) > 0:
                start_ms = int(idx.min().timestamp() * 1000)
                end_ms = int(idx.max().timestamp() * 1000)
                force = self.get_force_orders(symbol, limit=1000, start_time_ms=start_ms, end_time_ms=end_ms)
                if not force.empty:
                    bucket = force.resample(str(interval).lower()).sum()
                    out = out.join(bucket, how="left")
        except Exception as exc:
            logger.warning("historical_force_orders_fetch_failed symbol=%s err=%s", symbol, exc)

        # openInterest endpoint is snapshot-only; use latest snapshot and fallback CSV history when available.
        try:
            latest_oi = self.get_open_interest(symbol)
            if "open_interest" not in out.columns:
                out["open_interest"] = latest_oi
            else:
                out["open_interest"] = pd.to_numeric(out["open_interest"], errors="coerce").fillna(latest_oi)
        except Exception as exc:
            logger.warning("historical_open_interest_fetch_failed symbol=%s err=%s", symbol, exc)
            if "open_interest" not in out.columns:
                out["open_interest"] = 0.0

        for col in ["funding_rate", "liquidation_long_usd", "liquidation_short_usd"]:
            if col not in out.columns:
                out[col] = 0.0
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)

        out["open_interest"] = pd.to_numeric(out["open_interest"], errors="coerce").fillna(0.0)
        out = out.reindex(idx).ffill().fillna(0.0)
        return out

    async def get_flow_snapshot_async(self, symbol: str) -> dict[str, float]:
        return await asyncio.to_thread(self.get_flow_snapshot, symbol)
