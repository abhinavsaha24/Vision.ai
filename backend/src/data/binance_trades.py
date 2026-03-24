from __future__ import annotations

import logging
import io
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
import zipfile

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger(__name__)


@dataclass
class BinanceTradesConfig:
    base_url: str = "https://fapi.binance.com"
    spot_base_url: str = "https://api.binance.com"
    data_vision_base_url: str = "https://data.binance.vision"
    timeout_seconds: float = 10.0
    max_retries: int = 3
    retry_backoff_seconds: float = 0.8
    max_calls_per_request: int = 200
    max_window_ms: int = 2 * 60 * 60 * 1000
    call_sleep_seconds: float = 0.05
    throttle_sleep_seconds: float = 1.5


class BinanceTradesClient:
    """Fetches Binance futures aggTrades and derives microstructure features."""

    def __init__(self, config: BinanceTradesConfig | None = None):
        self.config = config or BinanceTradesConfig()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "vision-ai/binance-trades"})

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        s = str(symbol).upper().replace("/", "").replace("-", "")
        if s.endswith("USD") and not s.endswith("USDT"):
            s = s[:-3] + "USDT"
        if s.endswith("PERP"):
            s = s[:-4]
        return s

    def _request_json(self, endpoint: str, params: dict[str, Any], base_url: str | None = None) -> Any:
        url = f"{str(base_url or self.config.base_url)}{endpoint}"
        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.config.timeout_seconds)
                if response.status_code == 429:
                    time.sleep(self.config.throttle_sleep_seconds * attempt)
                    continue
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                last_error = exc
                if attempt >= self.config.max_retries:
                    break
                time.sleep(self.config.retry_backoff_seconds * attempt)
        raise RuntimeError(f"binance_trades_request_failed endpoint={endpoint} err={last_error}")

    def _download_data_vision_day(self, symbol: str, day: datetime) -> pd.DataFrame:
        day_str = day.strftime("%Y-%m-%d")
        filename = f"{symbol}-aggTrades-{day_str}.zip"
        url = (
            f"{self.config.data_vision_base_url}/data/futures/um/daily/aggTrades/"
            f"{symbol}/{filename}"
        )
        response = self.session.get(url, timeout=self.config.timeout_seconds)
        if response.status_code == 404:
            return pd.DataFrame()
        response.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            names = zf.namelist()
            if not names:
                return pd.DataFrame()
            with zf.open(names[0]) as fh:
                raw = pd.read_csv(fh, low_memory=False)

        frame = raw.copy()
        rename_map = {
            "a": "agg_trade_id",
            "agg_trade_id": "agg_trade_id",
            "p": "price",
            "price": "price",
            "q": "qty",
            "quantity": "qty",
            "f": "first_trade_id",
            "first_trade_id": "first_trade_id",
            "l": "last_trade_id",
            "last_trade_id": "last_trade_id",
            "T": "T",
            "transact_time": "T",
            "m": "m",
            "is_buyer_maker": "m",
            "M": "best_match",
            "best_match": "best_match",
        }
        frame.columns = [rename_map.get(str(c), str(c)) for c in frame.columns]

        required_defaults: dict[str, Any] = {
            "agg_trade_id": -1,
            "price": 0.0,
            "qty": 0.0,
            "first_trade_id": -1,
            "last_trade_id": -1,
            "T": 0,
            "m": False,
            "best_match": False,
        }
        for col, default in required_defaults.items():
            if col not in frame.columns:
                frame[col] = default

        frame["T"] = pd.to_numeric(frame["T"], errors="coerce")
        frame = frame.dropna(subset=["T"])
        frame["T"] = frame["T"].astype(int)
        if frame.empty:
            return pd.DataFrame()
        return frame

    def _fetch_data_vision_range(self, symbol: str, start_time_ms: int, end_time_ms: int) -> pd.DataFrame:
        start_dt = datetime.fromtimestamp(int(start_time_ms) / 1000.0, tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = datetime.fromtimestamp(int(end_time_ms) / 1000.0, tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        rows: list[pd.DataFrame] = []

        cur = start_dt
        while cur <= end_dt:
            try:
                day_df = self._download_data_vision_day(symbol=symbol, day=cur)
                if not day_df.empty:
                    rows.append(day_df)
            except Exception as exc:
                logger.warning("data_vision_day_fetch_failed symbol=%s day=%s err=%s", symbol, cur.date(), exc)
            cur = cur + timedelta(days=1)

        if not rows:
            return pd.DataFrame(columns=["price", "qty", "is_buyer_maker", "trade_id"])

        frame = pd.concat(rows, axis=0, ignore_index=True)
        frame["T"] = pd.to_numeric(frame["T"], errors="coerce").fillna(0).astype(int)
        frame = frame[(frame["T"] >= int(start_time_ms)) & (frame["T"] <= int(end_time_ms))]
        if frame.empty:
            return pd.DataFrame(columns=["price", "qty", "is_buyer_maker", "trade_id"])

        frame["ts"] = pd.to_datetime(frame["T"], unit="ms", utc=True)
        frame["price"] = pd.to_numeric(frame["price"], errors="coerce").fillna(0.0)
        frame["qty"] = pd.to_numeric(frame["qty"], errors="coerce").fillna(0.0)
        frame["trade_id"] = pd.to_numeric(frame["agg_trade_id"], errors="coerce").fillna(-1).astype(int)
        frame["is_buyer_maker"] = pd.Series(frame["m"], index=frame.index).astype(bool)
        frame["direction"] = np.where(frame["is_buyer_maker"], -1.0, 1.0)
        frame["signed_volume"] = frame["qty"] * frame["direction"]
        frame["notional"] = frame["price"] * frame["qty"]

        out = frame[["ts", "price", "qty", "is_buyer_maker", "trade_id", "direction", "signed_volume", "notional"]]
        out = out.sort_values("ts").drop_duplicates(subset=["trade_id"], keep="last")
        return out.reset_index(drop=True)

    def fetch_agg_trades(
        self,
        symbol: str,
        start_time_ms: int,
        end_time_ms: int,
        limit: int = 1000,
    ) -> pd.DataFrame:
        sym = self.normalize_symbol(symbol)

        # Prefer Data Vision for historical windows to avoid API throttling and truncation.
        window_ms = int(end_time_ms) - int(start_time_ms)
        if window_ms > int(self.config.max_window_ms):
            dv = self._fetch_data_vision_range(sym, start_time_ms=start_time_ms, end_time_ms=end_time_ms)
            if not dv.empty:
                return dv

        rows: list[dict[str, Any]] = []
        current = int(start_time_ms)
        end_ms = int(end_time_ms)
        calls = 0

        while current < end_ms and calls < int(self.config.max_calls_per_request):
            chunk_end = min(end_ms, current + int(self.config.max_window_ms))
            chunk_cursor = int(current)

            while chunk_cursor < chunk_end and calls < int(self.config.max_calls_per_request):
                params = {
                    "symbol": sym,
                    "startTime": int(chunk_cursor),
                    "endTime": int(chunk_end),
                    "limit": int(limit),
                }
                try:
                    payload = self._request_json("/fapi/v1/aggTrades", params, base_url=self.config.base_url)
                except Exception as exc:
                    # Fall back to spot aggTrades when futures endpoint is throttled.
                    if "rate_limited" in str(exc) or "429" in str(exc):
                        payload = self._request_json("/api/v3/aggTrades", params, base_url=self.config.spot_base_url)
                    else:
                        raise
                calls += 1
                if not isinstance(payload, list) or not payload:
                    break

                rows.extend(payload)
                last_ts = int(payload[-1].get("T", chunk_cursor))
                if last_ts <= chunk_cursor:
                    chunk_cursor += 1
                else:
                    chunk_cursor = last_ts + 1

                if len(payload) < int(limit):
                    break

                if self.config.call_sleep_seconds > 0:
                    time.sleep(self.config.call_sleep_seconds)

            current = chunk_end + 1
            if self.config.call_sleep_seconds > 0:
                time.sleep(self.config.call_sleep_seconds)

        if not rows:
            return pd.DataFrame(columns=["price", "qty", "is_buyer_maker", "trade_id"])

        frame = pd.DataFrame(rows)
        if "T" not in frame.columns:
            logger.warning("binance_trades_missing_timestamp_column symbol=%s", sym)
            return pd.DataFrame(columns=["price", "qty", "is_buyer_maker", "trade_id"])
        frame["ts"] = pd.to_datetime(frame["T"], unit="ms", utc=True)
        p_col = frame["p"] if "p" in frame.columns else pd.Series(0.0, index=frame.index)
        q_col = frame["q"] if "q" in frame.columns else pd.Series(0.0, index=frame.index)
        a_col = frame["a"] if "a" in frame.columns else pd.Series(-1, index=frame.index)
        m_col = frame["m"] if "m" in frame.columns else pd.Series(False, index=frame.index)

        frame["price"] = pd.to_numeric(p_col, errors="coerce").fillna(0.0)
        frame["qty"] = pd.to_numeric(q_col, errors="coerce").fillna(0.0)
        frame["trade_id"] = pd.to_numeric(a_col, errors="coerce").fillna(-1).astype(int)
        frame["is_buyer_maker"] = pd.Series(m_col, index=frame.index).astype(bool)

        # Binance m=true means buyer is maker => sell aggressor; false => buy aggressor.
        frame["direction"] = np.where(frame["is_buyer_maker"], -1.0, 1.0)
        frame["signed_volume"] = frame["qty"] * frame["direction"]
        frame["notional"] = frame["price"] * frame["qty"]

        out = frame[["ts", "price", "qty", "is_buyer_maker", "trade_id", "direction", "signed_volume", "notional"]]
        out = out.sort_values("ts").drop_duplicates(subset=["trade_id"], keep="last")
        return out.reset_index(drop=True)

    @staticmethod
    def build_execution_features(trades: pd.DataFrame, interval: str = "1h") -> pd.DataFrame:
        if trades.empty:
            return pd.DataFrame()

        t = trades.copy()
        t["ts"] = pd.to_datetime(t["ts"], utc=True)
        t = t.set_index("ts").sort_index()

        # 1-second base stream for rolling windows.
        t_index = pd.DatetimeIndex(pd.to_datetime(t.index, utc=True))
        sec = pd.DataFrame(index=t_index.floor("1s").unique().sort_values())
        sec["signed_volume"] = t["signed_volume"].resample("1s").sum().reindex(sec.index, fill_value=0.0)
        sec["total_volume"] = t["qty"].resample("1s").sum().reindex(sec.index, fill_value=0.0)
        sec["buy_volume"] = t["qty"].where(t["direction"] > 0.0, 0.0).resample("1s").sum().reindex(sec.index, fill_value=0.0)
        sec["sell_volume"] = t["qty"].where(t["direction"] < 0.0, 0.0).resample("1s").sum().reindex(sec.index, fill_value=0.0)
        sec["trade_count"] = t["trade_id"].resample("1s").count().reindex(sec.index, fill_value=0.0)
        sec["price_last"] = t["price"].resample("1s").last().reindex(sec.index).ffill()

        eps = 1e-9
        window_map = {"1s": 1, "5s": 5, "10s": 10, "30s": 30, "1m": 60}
        feat = pd.DataFrame(index=sec.index)

        for label, w in window_map.items():
            vol_w = sec["total_volume"].rolling(w).sum()
            buy_w = sec["buy_volume"].rolling(w).sum()
            sell_w = sec["sell_volume"].rolling(w).sum()
            signed_w = sec["signed_volume"].rolling(w).sum()
            trades_w = sec["trade_count"].rolling(w).sum()

            price_ref = sec["price_last"].shift(w)
            price_move = (sec["price_last"] / price_ref - 1.0).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            impact = (price_move.abs() / (vol_w + eps)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            imbalance = ((buy_w - sell_w) / (vol_w + eps)).replace([np.inf, -np.inf], np.nan).fillna(0.0)

            feat[f"trade_signed_volume_{label}"] = signed_w.fillna(0.0)
            feat[f"trade_buy_volume_{label}"] = buy_w.fillna(0.0)
            feat[f"trade_sell_volume_{label}"] = sell_w.fillna(0.0)
            feat[f"trade_imbalance_{label}"] = imbalance
            feat[f"trade_trades_per_second_{label}"] = (trades_w / max(float(w), 1.0)).fillna(0.0)
            feat[f"trade_volume_per_second_{label}"] = (vol_w / max(float(w), 1.0)).fillna(0.0)
            feat[f"trade_price_change_{label}"] = price_move
            feat[f"trade_impact_{label}"] = impact
            feat[f"trade_impact_efficiency_{label}"] = (price_move / (vol_w + eps)).replace([np.inf, -np.inf], np.nan).fillna(0.0)

            sv_std = signed_w.rolling(300).std().replace(0.0, np.nan)
            sv_z = ((signed_w - signed_w.rolling(300).mean()) / sv_std).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            feat[f"trade_signed_volume_z_{label}"] = sv_z

            # Shock taxonomy.
            sweep = (sv_z.abs() > 2.0) & (price_move.abs() > price_move.abs().rolling(300).quantile(0.65).fillna(0.0))
            absorption = (sv_z.abs() > 1.8) & (impact < impact.rolling(300).quantile(0.35).fillna(impact.median()))
            exhaustion = (sv_z.abs() > 1.8) & (impact < impact.shift(1).fillna(impact))

            feat[f"trade_sweep_flag_{label}"] = sweep.astype(float)
            feat[f"trade_absorption_flag_{label}"] = absorption.astype(float)
            feat[f"trade_exhaustion_flag_{label}"] = exhaustion.astype(float)

        # Core sub-minute microstructure states.
        svz5 = feat["trade_signed_volume_z_5s"].fillna(0.0)
        tps5 = feat["trade_trades_per_second_5s"].fillna(0.0)
        vps5 = feat["trade_volume_per_second_5s"].fillna(0.0)
        imb5 = feat["trade_imbalance_5s"].fillna(0.0)
        pchg5 = feat["trade_price_change_5s"].fillna(0.0)
        pchg10 = feat["trade_price_change_10s"].fillna(0.0)
        signed5 = feat["trade_signed_volume_5s"].fillna(0.0)
        impact5 = feat["trade_impact_5s"].fillna(0.0)
        impact_eff5 = feat["trade_impact_efficiency_5s"].fillna(0.0)

        q = lambda s, p: s.rolling(300).quantile(p).fillna(float(s.quantile(p) if len(s) > 0 else 0.0))
        high_sv = svz5.abs() > q(svz5.abs(), 0.70)
        high_density = tps5 > q(tps5, 0.70)
        high_concentration = vps5 > q(vps5, 0.70)
        rapid_move = pchg5.abs() > q(pchg5.abs(), 0.70)
        low_move = pchg5.abs() < q(pchg5.abs(), 0.40)
        low_impact = impact5 < q(impact5, 0.40)
        high_impact = impact5 > q(impact5, 0.60)

        # Requested microstructure signals.
        feat["trade_aggression_burst_5s"] = (high_sv & high_density).astype(float)
        feat["trade_sweep_detection_5s"] = (rapid_move & high_concentration).astype(float)
        feat["trade_absorption_5s"] = (high_concentration & low_move).astype(float)
        feat["trade_impact_efficiency_5s"] = impact_eff5

        # Requested event taxonomy (A-D).
        strong_buy_imb = imb5 > q(imb5, 0.70)
        strong_sell_imb = imb5 < q(imb5, 0.30)
        strong_up = pchg5 > q(pchg5, 0.70)
        strong_down = pchg5 < q(pchg5, 0.30)

        event_a = strong_buy_imb & strong_up
        event_b = strong_sell_imb & strong_down
        event_c = feat["trade_absorption_5s"] > 0.0
        repeated_aggression = feat["trade_aggression_burst_5s"].rolling(30).sum().fillna(0.0) >= 2.0
        weakening_impact = impact5 < impact5.shift(1).fillna(impact5)
        event_d = repeated_aggression & weakening_impact

        feat["trade_event_a_buy_sweep"] = event_a.astype(float)
        feat["trade_event_b_sell_sweep"] = event_b.astype(float)
        feat["trade_event_c_absorption"] = event_c.astype(float)
        feat["trade_event_d_exhaustion"] = event_d.astype(float)

        # Sequence logic.
        burst = feat["trade_aggression_burst_5s"] > 0.0
        burst_to_burst = burst & burst.shift(1).fillna(False)
        continuation = pchg10.abs() > q(pchg10.abs(), 0.60)
        feat["trade_sequence_burst_burst_continuation"] = (burst_to_burst & continuation).astype(float)

        burst_recent = burst.rolling(20).max().fillna(0.0) > 0.0
        reversal_vs_burst = (event_c & burst_recent & ((pchg10 * np.sign(signed5)) < -q(pchg10.abs(), 0.55)))
        feat["trade_sequence_burst_absorption_reversal"] = reversal_vs_burst.astype(float)

        # Response model: event-conditioned forward returns at 5s/30s/60s.
        fwd_5s = (sec["price_last"].shift(-5) / sec["price_last"] - 1.0).replace([np.inf, -np.inf], np.nan)
        fwd_30s = (sec["price_last"].shift(-30) / sec["price_last"] - 1.0).replace([np.inf, -np.inf], np.nan)
        fwd_60s = (sec["price_last"].shift(-60) / sec["price_last"] - 1.0).replace([np.inf, -np.inf], np.nan)

        for name, ev in {
            "a": event_a,
            "b": event_b,
            "c": event_c,
            "d": event_d,
        }.items():
            feat[f"trade_event_{name}_count"] = ev.astype(float)
            feat[f"trade_event_{name}_fwd_5s"] = fwd_5s.where(ev)
            feat[f"trade_event_{name}_fwd_30s"] = fwd_30s.where(ev)
            feat[f"trade_event_{name}_fwd_60s"] = fwd_60s.where(ev)

        feat["trade_event_a_response_score"] = feat[["trade_event_a_fwd_5s", "trade_event_a_fwd_30s", "trade_event_a_fwd_60s"]].mean(axis=1).fillna(0.0)
        feat["trade_event_b_response_score"] = feat[["trade_event_b_fwd_5s", "trade_event_b_fwd_30s", "trade_event_b_fwd_60s"]].mean(axis=1).fillna(0.0)
        feat["trade_event_c_response_score"] = feat[["trade_event_c_fwd_5s", "trade_event_c_fwd_30s", "trade_event_c_fwd_60s"]].mean(axis=1).fillna(0.0)
        feat["trade_event_d_response_score"] = feat[["trade_event_d_fwd_5s", "trade_event_d_fwd_30s", "trade_event_d_fwd_60s"]].mean(axis=1).fillna(0.0)

        # 1m response metrics used in edge classification.
        feat["trade_recovery_1m"] = (-feat["trade_price_change_1m"]).rolling(60).mean().fillna(0.0)
        feat["trade_shock_cluster_1m"] = feat["trade_sweep_flag_1m"].rolling(60).sum().fillna(0.0)

        any_shock = feat["trade_sweep_flag_1m"] > 0.5
        shock_int = any_shock.astype(int)
        feat["trade_time_since_shock_1m"] = (~any_shock).astype(int).groupby(shock_int.cumsum()).cumsum().astype(float)

        # Collapse per-second features to target bar interval.
        sum_cols = [
            c
            for c in feat.columns
            if c.endswith("_flag_1s")
            or c.endswith("_flag_5s")
            or c.endswith("_flag_10s")
            or c.endswith("_flag_30s")
            or c.endswith("_flag_1m")
            or c.endswith("_count")
            or ("signed_volume" in c and "_z_" not in c)
            or "buy_volume" in c
            or "sell_volume" in c
            or "shock_cluster" in c
            or "sequence_" in c
        ]
        last_cols = [c for c in feat.columns if "time_since" in c]
        mean_cols = [c for c in feat.columns if c not in set(sum_cols + last_cols)]

        out = pd.DataFrame()
        if sum_cols:
            out = feat[sum_cols].resample(str(interval).lower()).sum()
        if mean_cols:
            mean_part = feat[mean_cols].resample(str(interval).lower()).mean()
            out = mean_part if out.empty else out.join(mean_part, how="outer")
        if last_cols:
            last_part = feat[last_cols].resample(str(interval).lower()).last()
            out = last_part if out.empty else out.join(last_part, how="outer")

        out = out.replace([np.inf, -np.inf], np.nan)
        return out.ffill().fillna(0.0)
