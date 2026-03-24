from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

from backend.src.data.binance_trades import BinanceTradesClient

logger = logging.getLogger(__name__)


@dataclass
class MarketContextConfig:
    binance_base_url: str = "https://fapi.binance.com"
    request_timeout: float = 8.0


class MarketContextFetcher:
    """Fetches and engineers positioning/session context for 1H alpha research."""

    def __init__(self, config: MarketContextConfig | None = None):
        self.config = config or MarketContextConfig()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "vision-ai/market-context"})
        self.trades_client = BinanceTradesClient()

    @staticmethod
    def _to_binance_symbol(symbol: str) -> str:
        s = str(symbol).upper().replace("/", "").replace("-", "")
        if s.endswith("BUSD"):
            return s
        if s.endswith("USD") and not s.endswith(("USDT", "BUSD")):
            s = s[:-3] + "USDT"
        if s.endswith("PERP"):
            s = s[:-4]
        return s

    @staticmethod
    def _interval_to_binance_period(interval: str) -> str:
        v = str(interval).lower().strip()
        if v in {"1h", "60m"}:
            return "1h"
        if v in {"4h", "240m"}:
            return "4h"
        if v in {"1d", "24h"}:
            return "1d"
        return "1h"

    @staticmethod
    def _flow_dataset_path(symbol: str, interval: str) -> Path:
        base_dir = Path(os.getenv("FLOW_DATA_DIR", "data/flow"))
        base_dir = base_dir if base_dir.is_absolute() else Path.cwd() / base_dir
        normalized = MarketContextFetcher._to_binance_symbol(symbol)
        return base_dir / f"{normalized}_{str(interval).lower()}.parquet"

    @classmethod
    def _load_flow_parquet(cls, symbol: str, interval: str) -> pd.DataFrame:
        path = cls._flow_dataset_path(symbol=symbol, interval=interval)
        if not path.exists():
            return pd.DataFrame()
        try:
            df = pd.read_parquet(path)
            if df.empty:
                return pd.DataFrame()
            if "ts" in df.columns:
                df["ts"] = pd.to_datetime(df["ts"], utc=True)
                df = df.set_index("ts")
            else:
                df.index = pd.to_datetime(df.index, utc=True)
            return df.sort_index()
        except Exception as exc:
            logger.warning("flow_parquet_load_failed path=%s err=%s", path, exc)
            return pd.DataFrame()

    def _get_json(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        url = f"{self.config.binance_base_url}{path}"
        response = self.session.get(url, params=params, timeout=self.config.request_timeout)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and "code" in data and "msg" in data:
            raise RuntimeError(f"binance_error path={path} params={params} payload={data}")
        if not isinstance(data, list):
            return []
        return data

    def _fetch_open_interest(self, symbol: str, period: str, limit: int = 500) -> pd.DataFrame:
        rows = self._get_json(
            "/futures/data/openInterestHist",
            {"symbol": symbol, "period": period, "limit": int(limit)},
        )
        if not rows:
            return pd.DataFrame(columns=["open_interest", "open_interest_value"])
        df = pd.DataFrame(rows)
        df["ts"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        out = pd.DataFrame(index=df["ts"])
        out["open_interest"] = pd.to_numeric(df.get("sumOpenInterest", pd.Series(0.0, index=df.index)), errors="coerce").to_numpy()
        out["open_interest_value"] = pd.to_numeric(df.get("sumOpenInterestValue", pd.Series(0.0, index=df.index)), errors="coerce").to_numpy()
        return out.sort_index()

    def _fetch_funding_rate(self, symbol: str, limit: int = 1000) -> pd.DataFrame:
        rows = self._get_json(
            "/fapi/v1/fundingRate",
            {"symbol": symbol, "limit": int(limit)},
        )
        if not rows:
            return pd.DataFrame(columns=["funding_rate"])
        df = pd.DataFrame(rows)
        df["ts"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
        out = pd.DataFrame(index=df["ts"])
        out["funding_rate"] = pd.to_numeric(df.get("fundingRate", pd.Series(0.0, index=df.index)), errors="coerce").to_numpy()
        return out.sort_index()

    def _fetch_long_short_ratio(self, symbol: str, period: str, limit: int = 500) -> pd.DataFrame:
        rows = self._get_json(
            "/futures/data/globalLongShortAccountRatio",
            {"symbol": symbol, "period": period, "limit": int(limit)},
        )
        if not rows:
            return pd.DataFrame(columns=["long_short_ratio", "long_account", "short_account"])
        df = pd.DataFrame(rows)
        df["ts"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        out = pd.DataFrame(index=df["ts"])
        out["long_short_ratio"] = pd.to_numeric(df.get("longShortRatio", pd.Series(1.0, index=df.index)), errors="coerce").to_numpy()
        out["long_account"] = pd.to_numeric(df.get("longAccount", pd.Series(0.0, index=df.index)), errors="coerce").to_numpy()
        out["short_account"] = pd.to_numeric(df.get("shortAccount", pd.Series(0.0, index=df.index)), errors="coerce").to_numpy()
        return out.sort_index()

    def _fetch_liquidations(self) -> pd.DataFrame:
        csv_path = os.getenv("LIQUIDATION_DATA_CSV", "").strip()
        if not csv_path:
            return pd.DataFrame(columns=["liquidation_long_usd", "liquidation_short_usd"])
        try:
            df = pd.read_csv(csv_path)
            if "ts" not in df.columns:
                return pd.DataFrame(columns=["liquidation_long_usd", "liquidation_short_usd"])
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
            out = pd.DataFrame(index=df["ts"])
            liq_long = df["liquidation_long_usd"] if "liquidation_long_usd" in df.columns else pd.Series(0.0, index=df.index)
            liq_short = df["liquidation_short_usd"] if "liquidation_short_usd" in df.columns else pd.Series(0.0, index=df.index)
            out["liquidation_long_usd"] = pd.to_numeric(liq_long, errors="coerce").fillna(0.0).to_numpy()
            out["liquidation_short_usd"] = pd.to_numeric(liq_short, errors="coerce").fillna(0.0).to_numpy()
            return out.sort_index()
        except Exception as exc:
            logger.warning("liquidation_feed_load_failed: %s", exc)
            return pd.DataFrame(columns=["liquidation_long_usd", "liquidation_short_usd"])

    def _fetch_trade_microstructure(self, symbol: str, index: pd.DatetimeIndex, interval: str) -> pd.DataFrame:
        if len(index) == 0:
            return pd.DataFrame()
        try:
            start_ms = int(index.min().timestamp() * 1000)
            end_ms = int(index.max().timestamp() * 1000)
            trades = self.trades_client.fetch_agg_trades(symbol=symbol, start_time_ms=start_ms, end_time_ms=end_ms)
            if trades.empty:
                return pd.DataFrame()
            features = self.trades_client.build_execution_features(trades, interval=interval)
            if features.empty:
                return pd.DataFrame()
            features.index = pd.DatetimeIndex(pd.to_datetime(features.index, utc=True))
            return features.sort_index()
        except Exception as exc:
            logger.warning("trade_microstructure_fetch_failed symbol=%s err=%s", symbol, exc)
            return pd.DataFrame()

    @staticmethod
    def _load_positioning_csv() -> pd.DataFrame:
        csv_path = os.getenv("POSITIONING_DATA_CSV", "").strip()
        if not csv_path:
            return pd.DataFrame()
        try:
            df = pd.read_csv(csv_path)
            if "ts" not in df.columns:
                return pd.DataFrame()
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
            out = df.set_index("ts").sort_index()
            keep = [
                "open_interest",
                "funding_rate",
                "long_short_ratio",
                "liquidation_long_usd",
                "liquidation_short_usd",
            ]
            for col in keep:
                if col not in out.columns:
                    out[col] = 0.0
                out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
            return out[keep]
        except Exception as exc:
            logger.warning("positioning_csv_load_failed: %s", exc)
            return pd.DataFrame()

    @staticmethod
    def _session_columns(index: pd.DatetimeIndex) -> pd.DataFrame:
        hour = index.hour
        out = pd.DataFrame(index=index)
        out["session_asia"] = ((hour >= 0) & (hour < 8)).astype(float)
        out["session_eu"] = ((hour >= 8) & (hour < 16)).astype(float)
        out["session_us"] = ((hour >= 13) & (hour < 21)).astype(float)
        out["is_weekend"] = (index.dayofweek >= 5).astype(float)
        out["hour_sin"] = np.sin((2.0 * np.pi * hour) / 24.0)
        out["hour_cos"] = np.cos((2.0 * np.pi * hour) / 24.0)
        return out

    def enrich_ohlcv(
        self,
        df: pd.DataFrame,
        symbol: str,
        interval: str = "1h",
        lookback_limit: int = 1000,
    ) -> pd.DataFrame:
        if df.empty:
            return df

        frame = df.copy().sort_index()
        idx = pd.DatetimeIndex(pd.to_datetime(frame.index, utc=True))
        frame.index = idx

        period = self._interval_to_binance_period(interval)
        fut_symbol = self._to_binance_symbol(symbol)

        context_parts: list[pd.DataFrame] = []
        persisted_ctx = self._load_flow_parquet(symbol=fut_symbol, interval=interval)
        allow_live_fallback = str(os.getenv("ALLOW_LIVE_FLOW_FALLBACK", "0")).strip().lower() in {"1", "true", "yes"}
        if not persisted_ctx.empty:
            context_parts.append(persisted_ctx)

        if allow_live_fallback:
            try:
                context_parts.append(self._fetch_open_interest(fut_symbol, period, limit=lookback_limit))
            except Exception as exc:
                logger.warning("open_interest_fetch_failed: %s", exc)
            try:
                context_parts.append(self._fetch_funding_rate(fut_symbol, limit=min(lookback_limit * 2, 1000)))
            except Exception as exc:
                logger.warning("funding_fetch_failed: %s", exc)
            try:
                context_parts.append(self._fetch_long_short_ratio(fut_symbol, period, limit=lookback_limit))
            except Exception as exc:
                logger.warning("long_short_ratio_fetch_failed: %s", exc)

            trade_ctx = self._fetch_trade_microstructure(fut_symbol, index=idx, interval=interval)
            if not trade_ctx.empty:
                context_parts.append(trade_ctx)

        liq = self._fetch_liquidations()
        if not liq.empty:
            context_parts.append(liq)

        csv_ctx = self._load_positioning_csv()
        if not csv_ctx.empty:
            context_parts.append(csv_ctx)

        if context_parts:
            context = pd.concat(context_parts, axis=1).sort_index()
            context = context[~context.index.duplicated(keep="last")]
            context = context.reindex(frame.index, method="ffill")
            frame = frame.join(context, how="left")
            frame = frame.loc[:, ~frame.columns.duplicated(keep="last")]

        if "open_interest" not in frame.columns:
            frame["open_interest"] = 0.0
        if "open_interest_value" not in frame.columns:
            frame["open_interest_value"] = 0.0
        if "funding_rate" not in frame.columns:
            frame["funding_rate"] = 0.0
        if "long_short_ratio" not in frame.columns:
            frame["long_short_ratio"] = 1.0
        if "liquidation_long_usd" not in frame.columns:
            frame["liquidation_long_usd"] = 0.0
        if "liquidation_short_usd" not in frame.columns:
            frame["liquidation_short_usd"] = 0.0

        session = self._session_columns(idx)
        for col in session.columns:
            if col in frame.columns:
                frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(session[col])
            else:
                frame[col] = session[col]

        vol = frame["volume"].astype(float).replace(0.0, np.nan)
        index_diffs = frame.index.to_series().diff().dropna()
        bar_hours = 1.0
        if not index_diffs.empty:
            inferred = float(index_diffs.dt.total_seconds().median() / 3600.0)
            if np.isfinite(inferred) and inferred > 0.0:
                bar_hours = inferred
        window_24h = max(1, int(round(24.0 / bar_hours)))
        window_12h = max(1, int(round(12.0 / bar_hours)))
        vwap_roll = (frame["close"].astype(float) * vol).rolling(window_24h).sum() / vol.rolling(window_24h).sum()
        frame["vwap_24h"] = vwap_roll.fillna(frame["close"].astype(float))
        frame["value_area_distance"] = (
            (frame["close"].astype(float) - frame["vwap_24h"].astype(float))
            / frame["close"].astype(float).replace(0.0, np.nan)
        ).replace([np.inf, -np.inf], np.nan).fillna(0.0)

        ret1 = frame["close"].astype(float).pct_change().fillna(0.0)
        frame["realized_vol_12h"] = ret1.rolling(window_12h).std().fillna(0.0)
        by_hour = frame.groupby(idx.hour)["realized_vol_12h"].transform("median").replace(0.0, np.nan)
        frame["vol_cluster_score"] = (frame["realized_vol_12h"] / by_hour).replace([np.inf, -np.inf], np.nan).fillna(1.0)

        numeric_cols = [
            "open_interest",
            "open_interest_value",
            "funding_rate",
            "long_short_ratio",
            "long_account",
            "short_account",
            "liquidation_long_usd",
            "liquidation_short_usd",
            "session_asia",
            "session_eu",
            "session_us",
            "is_weekend",
            "hour_sin",
            "hour_cos",
            "vwap_24h",
            "value_area_distance",
            "realized_vol_12h",
            "vol_cluster_score",
        ]
        numeric_cols.extend([c for c in frame.columns if str(c).startswith("trade_")])
        for col in numeric_cols:
            if col in frame.columns:
                col_values = frame[col]
                if isinstance(col_values, pd.DataFrame):
                    col_values = pd.Series(col_values.to_numpy()[:, -1], index=frame.index)
                elif not isinstance(col_values, pd.Series):
                    col_values = pd.Series(col_values, index=frame.index)
                frame[col] = pd.to_numeric(col_values, errors="coerce").replace([np.inf, -np.inf], np.nan)

        return frame.ffill().fillna(0.0)
