from __future__ import annotations

import numpy as np
import pandas as pd

from .schema import (
    DERIV_BASIS,
    DERIV_FUNDING,
    DERIV_OPEN_INTEREST,
    EVENT_LIQUIDATIONS,
    EVENT_VOL_SHOCK,
    MICRO_ORDERBOOK,
    MICRO_TRADES,
)
from .storage import TimeSeriesStore


def build_feature_table(store: TimeSeriesStore, symbol: str, cross_assets: list[str]) -> pd.DataFrame:
    orderbook = _source_to_series(store.read_source(MICRO_ORDERBOOK, symbol), "ob")
    trades = _source_to_series(store.read_source(MICRO_TRADES, symbol), "tr")
    funding = _source_to_series(store.read_source(DERIV_FUNDING, symbol), "fund")
    oi = _source_to_series(store.read_source(DERIV_OPEN_INTEREST, symbol), "oi")
    basis = _source_to_series(store.read_source(DERIV_BASIS, symbol), "basis")
    liq = _source_to_series(store.read_source(EVENT_LIQUIDATIONS, symbol), "liq")
    vol_shock = _source_to_series(store.read_source(EVENT_VOL_SHOCK, symbol), "vshock")

    frames = [orderbook, trades, funding, oi, basis, liq, vol_shock]

    for asset in cross_assets:
        c = store.read_source("cross_asset_close", asset)
        if c.empty:
            continue
        cc = _source_to_series(c, f"cross_{asset.replace('-', '_').lower()}")
        frames.append(cc)

    base = _outer_merge_on_ts(frames)
    if base.empty:
        return base

    base = base.sort_values("ts").drop_duplicates(subset=["ts"], keep="last").reset_index(drop=True)
    base["ts"] = pd.to_datetime(base["ts"], utc=True, errors="coerce").dt.floor("h")
    base = base.dropna(subset=["ts"]).sort_values("ts")

    # Canonical hourly timeline avoids cross-source drift and makes retrieval deterministic.
    canonical = pd.DataFrame({"ts": pd.date_range(base["ts"].min(), base["ts"].max(), freq="1h", tz="UTC")})
    base = canonical.merge(base, on="ts", how="left")

    ffill_cols = [
        "ob_v1",
        "ob_v2",
        "ob_v3",
        "ob_v4",
        "tr_v4",
        "fund_value",
        "oi_value",
        "oi_v2",
        "basis_value",
        "basis_v1",
        "basis_v2",
    ]
    zero_cols = [c for c in base.columns if c not in {"ts", *ffill_cols}]
    for c in ffill_cols:
        if c in base.columns:
            base[c] = pd.to_numeric(base[c], errors="coerce").ffill().bfill()
    for c in zero_cols:
        if c in base.columns:
            base[c] = pd.to_numeric(base[c], errors="coerce").fillna(0.0)

    # Order flow features
    base["ofi"] = _series_or_default(base, "ob_value")
    base["aggressor_imbalance"] = _series_or_default(base, "tr_v1")

    # Liquidity features
    bid = _series_or_default(base, "ob_v1")
    ask = _series_or_default(base, "ob_v2")
    spread = _series_or_default(base, "ob_v3")
    base["depth_imbalance"] = (bid - ask) / (bid + ask + 1e-12)
    base["liquidity_vacuum"] = ((bid + ask).pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0) < -0.20).astype(float)
    base["spread_expansion"] = (spread > spread.rolling(72, min_periods=24).quantile(0.8)).astype(float)

    # Positioning features
    base["oi_change"] = _series_or_default(base, "oi_v1")
    base["funding_rate"] = _series_or_default(base, "fund_value")
    base["basis"] = _series_or_default(base, "basis_value")
    base["funding_crowding"] = (base["funding_rate"] * base["oi_change"]).fillna(0.0)
    base["oi_divergence"] = (base["oi_change"] - base["basis"].pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)).fillna(0.0)

    # Event features
    base["liquidation_pressure"] = _series_or_default(base, "liq_value")
    base["liquidation_count"] = _series_or_default(base, "liq_v1")
    base["volatility_shock_z"] = _series_or_default(base, "vshock_value")
    base["volatility_shock_flag"] = _series_or_default(base, "vshock_v1")

    # Labeling-only helper (for univariate tests, not strategy logic)
    perp_close = _series_or_default(base, "basis_v1").replace(0.0, np.nan).ffill().bfill()
    base["target_return_3h"] = (perp_close.shift(-3) / (perp_close + 1e-12) - 1.0).fillna(0.0)

    return base


def _source_to_series(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["ts"])
    out = df.copy()
    out["ts"] = pd.to_datetime(out["ts"], utc=True, errors="coerce").dt.floor("h")
    out = out.dropna(subset=["ts"]).sort_values("ts")
    out = out.rename(
        columns={
            "value": f"{prefix}_value",
            "v1": f"{prefix}_v1",
            "v2": f"{prefix}_v2",
            "v3": f"{prefix}_v3",
            "v4": f"{prefix}_v4",
        }
    )
    keep = [c for c in ["ts", f"{prefix}_value", f"{prefix}_v1", f"{prefix}_v2", f"{prefix}_v3", f"{prefix}_v4"] if c in out.columns]
    return out[keep]


def _outer_merge_on_ts(frames: list[pd.DataFrame]) -> pd.DataFrame:
    merged = None
    for f in frames:
        if f.empty:
            continue
        merged = f if merged is None else merged.merge(f, on="ts", how="outer")
    return merged if merged is not None else pd.DataFrame(columns=["ts"])


def _series_or_default(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return pd.Series(0.0, index=df.index)
