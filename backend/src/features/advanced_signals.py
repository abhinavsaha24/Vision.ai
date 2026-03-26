"""Institutional alpha signal extensions (20+ orthogonal signals)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _safe_series(s: pd.Series) -> pd.Series:
    return s.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def add_institutional_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Add advanced cross-horizon, flow, structure, and regime-aware alpha signals."""
    out = df.copy()
    close = out["close"].astype(float)
    high = out["high"].astype(float)
    low = out["low"].astype(float)
    vol = out["volume"].astype(float).replace(0, np.nan).fillna(1.0)
    ret = close.pct_change().fillna(0.0)

    # 1-5: Multi-horizon momentum
    out["mom_3d"] = _safe_series(close.pct_change(3))
    out["mom_7d"] = _safe_series(close.pct_change(7))
    out["mom_14d"] = _safe_series(close.pct_change(14))
    out["mom_30d"] = _safe_series(close.pct_change(30))
    out["mom_90d"] = _safe_series(close.pct_change(90))

    # 6-8: Volume-pressure and signed flow proxies
    signed_flow = np.sign(ret) * vol
    signed_flow_s = pd.Series(signed_flow, index=out.index)
    out["signed_flow_5"] = _safe_series(signed_flow_s.rolling(5, min_periods=1).sum())
    out["signed_flow_20"] = _safe_series(signed_flow_s.rolling(20, min_periods=1).sum())
    out["flow_imbalance"] = _safe_series(
        (signed_flow_s / vol).rolling(10, min_periods=1).mean()
    )

    # 9-11: Realized vol term structure
    rv_5 = ret.rolling(5, min_periods=2).std()
    rv_20 = ret.rolling(20, min_periods=5).std()
    rv_60 = ret.rolling(60, min_periods=10).std()
    out["rv_5"] = _safe_series(rv_5)
    out["rv_20"] = _safe_series(rv_20)
    out["vol_term_5_20"] = _safe_series(rv_5 / rv_20.replace(0, np.nan))

    # 12-14: Trend stability and acceleration
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    out["trend_strength"] = _safe_series((ema20 - ema50) / ema50.replace(0, np.nan))
    out["trend_accel"] = _safe_series(out["trend_strength"].diff(3))
    out["price_accel"] = _safe_series(ret.diff(2))

    # 15-17: Intraday range and close location value
    tr = (high - low).replace(0, np.nan)
    out["range_pct"] = _safe_series(tr / close.replace(0, np.nan))
    out["clv"] = _safe_series(((close - low) - (high - close)) / tr)
    out["range_compression_10"] = _safe_series(
        out["range_pct"].rolling(10, min_periods=1).mean()
    )

    # 18-20: Microstructure-inspired features
    out["gap_return"] = (
        _safe_series(out["open"].astype(float).pct_change())
        if "open" in out.columns
        else 0.0
    )
    out["reversal_1d"] = _safe_series(-ret.shift(1) * ret)
    out["noise_ratio"] = _safe_series(
        ret.abs().rolling(10, min_periods=1).sum()
        / (close.diff(10).abs().replace(0, np.nan))
    )

    # 21-23: Cross-asset features if benchmark columns are present
    if "eth_close" in out.columns:
        eth_ret = out["eth_close"].astype(float).pct_change().fillna(0.0)
        out["btc_eth_momentum_spread"] = _safe_series(
            ret.rolling(10, min_periods=1).mean()
            - eth_ret.rolling(10, min_periods=1).mean()
        )
        out["btc_eth_corr_30"] = _safe_series(
            ret.rolling(30, min_periods=10).corr(eth_ret)
        )
    else:
        out["btc_eth_momentum_spread"] = 0.0
        out["btc_eth_corr_30"] = 0.0

    if "spy_close" in out.columns:
        spy_ret = out["spy_close"].astype(float).pct_change().fillna(0.0)
        out["crypto_equity_corr_30"] = _safe_series(
            ret.rolling(30, min_periods=10).corr(spy_ret)
        )
    else:
        out["crypto_equity_corr_30"] = 0.0

    # 24-25: Tail/left-risk signals
    out["downside_vol_20"] = _safe_series(
        ret.where(ret < 0, 0).rolling(20, min_periods=3).std()
    )
    out["tail_ratio_20"] = _safe_series(
        ret.rolling(20, min_periods=10).quantile(0.95).abs()
        / ret.rolling(20, min_periods=10).quantile(0.05).abs().replace(0, np.nan)
    )

    # 26: Regime transition pressure
    out["regime_transition_pressure"] = _safe_series(
        (out["rv_5"] - out["rv_20"]).diff(2)
    )

    return out
