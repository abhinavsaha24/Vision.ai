"""
Research-grade alpha features for crypto trading.

Categories:
  1. Order Flow & Microstructure (from OHLCV proxies + order book when available)
  2. Volume Intelligence (signed flow, smart money, accumulation/distribution)
  3. Derivatives Data (funding rate, open interest — when available)
  4. Regime & Structure (Hurst, efficiency ratio, entropy, cross-timeframe)
  5. Statistical Edge (autocorrelation decay, tail ratios, mean-reversion speed)

All features use PAST DATA ONLY. No lookahead bias.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ==================================================================
# Utilities
# ==================================================================

def _safe(s: pd.Series) -> pd.Series:
    """Replace inf/nan with 0."""
    return s.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _zscore(s: pd.Series, window: int = 20) -> pd.Series:
    """Rolling z-score."""
    mu = s.rolling(window, min_periods=max(1, window // 2)).mean()
    sd = s.rolling(window, min_periods=max(1, window // 2)).std().replace(0, 1e-8)
    return _safe((s - mu) / sd)


def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


# ==================================================================
# 1. ORDER FLOW & MICROSTRUCTURE
# ==================================================================

def add_order_flow_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Order flow features derived from OHLCV data.
    When order book data is available in columns 'bid_volume'/'ask_volume',
    uses actual book data instead of proxies.
    """
    out = df.copy()
    close = out["close"].astype(float)
    high = out["high"].astype(float)
    low = out["low"].astype(float)
    volume = out["volume"].astype(float).replace(0, np.nan).fillna(1.0)
    rng = (high - low).replace(0, 1e-8)

    # --- Close Location Value (where did price close within the bar?) ---
    clv = ((close - low) - (high - close)) / rng
    out["of_clv"] = _safe(clv)

    # --- Buy/Sell volume estimation (Bulkowski method) ---
    buy_pct = (close - low) / rng
    sell_pct = (high - close) / rng
    out["of_buy_volume"] = _safe(buy_pct * volume)
    out["of_sell_volume"] = _safe(sell_pct * volume)

    # --- Volume Delta (buy - sell) ---
    vdelta = out["of_buy_volume"] - out["of_sell_volume"]
    out["of_volume_delta"] = _safe(vdelta)
    out["of_volume_delta_zscore"] = _zscore(vdelta, 20)

    # --- Cumulative Volume Delta ---
    out["of_cvd_20"] = _safe(vdelta.rolling(20, min_periods=1).sum())
    out["of_cvd_50"] = _safe(vdelta.rolling(50, min_periods=1).sum())

    # --- Order Book Imbalance (if available, otherwise proxy) ---
    if "bid_volume" in out.columns and "ask_volume" in out.columns:
        bid_v = out["bid_volume"].astype(float).replace(0, 1e-8)
        ask_v = out["ask_volume"].astype(float).replace(0, 1e-8)
        imb = (bid_v - ask_v) / (bid_v + ask_v)
        out["of_ob_imbalance"] = _safe(imb)
        out["of_ob_imbalance_zscore"] = _zscore(imb, 20)
    else:
        # Proxy from CLV
        out["of_ob_imbalance"] = _safe(clv.rolling(5, min_periods=1).mean())
        out["of_ob_imbalance_zscore"] = _zscore(
            clv.rolling(5, min_periods=1).mean(), 20
        )

    # --- Trade Flow Toxicity (VPIN proxy) ---
    # VPIN = |buy_vol - sell_vol| / total_vol, rolling
    abs_delta = vdelta.abs()
    out["of_vpin_20"] = _safe(
        abs_delta.rolling(20, min_periods=1).mean()
        / volume.rolling(20, min_periods=1).mean().replace(0, 1e-8)
    )

    # --- Kyle's Lambda (price impact = |return| / volume) ---
    ret = close.pct_change().fillna(0)
    dollar_vol = close * volume
    out["of_kyle_lambda"] = _safe(
        ret.abs().rolling(20, min_periods=1).mean()
        / dollar_vol.rolling(20, min_periods=1).mean().replace(0, 1e-8)
        * 1e6  # Scale for readability
    )

    # --- Amihud Illiquidity (rolling) ---
    out["of_amihud"] = _safe(
        (ret.abs() / dollar_vol.replace(0, 1e-8)).rolling(20, min_periods=1).mean()
        * 1e8
    )
    out["of_amihud_zscore"] = _zscore(out["of_amihud"], 50)

    # --- Bid-Ask Spread Proxy (Corwin-Schultz High-Low estimator) ---
    log_hl = np.log(high / low.replace(0, 1e-8))
    beta = log_hl ** 2 + log_hl.shift(1) ** 2
    h2 = high.rolling(2, min_periods=1).max()
    l2 = low.rolling(2, min_periods=1).min()
    gamma = np.log(h2 / l2.replace(0, 1e-8)) ** 2
    denom = 3 - 2 * np.sqrt(2)
    alpha_raw = (np.sqrt(2 * beta) - np.sqrt(beta)) / denom - np.sqrt(
        gamma / denom
    )
    alpha_raw = _safe(alpha_raw.clip(-1, 1))
    spread = 2 * (np.exp(alpha_raw) - 1) / (1 + np.exp(alpha_raw))
    out["of_spread_cs"] = _safe(spread.clip(0, 0.05))
    out["of_spread_zscore"] = _zscore(out["of_spread_cs"], 50)

    return out


# ==================================================================
# 2. VOLUME INTELLIGENCE
# ==================================================================

def add_volume_features(df: pd.DataFrame) -> pd.DataFrame:
    """Advanced volume-based alpha signals."""
    out = df.copy()
    close = out["close"].astype(float)
    volume = out["volume"].astype(float).replace(0, np.nan).fillna(1.0)
    ret = close.pct_change().fillna(0)

    # --- On-Balance Volume (OBV) ---
    signed_vol = np.where(ret > 0, volume, np.where(ret < 0, -volume, 0))
    obv = pd.Series(np.cumsum(signed_vol), index=out.index)
    out["vi_obv_zscore"] = _zscore(obv, 20)
    out["vi_obv_slope"] = _safe(obv.diff(5) / obv.rolling(20, min_periods=1).std().replace(0, 1e-8))

    # --- Accumulation/Distribution Line ---
    mfm = ((close - out["low"]) - (out["high"] - close)) / (
        (out["high"] - out["low"]).replace(0, 1e-8)
    )
    ad = (mfm * volume).cumsum()
    out["vi_ad_zscore"] = _zscore(ad, 20)

    # --- Money Flow Index (volume-weighted RSI) ---
    typical_price = (out["high"] + out["low"] + close) / 3
    raw_mf = typical_price * volume
    pos_mf = raw_mf.where(typical_price > typical_price.shift(1), 0)
    neg_mf = raw_mf.where(typical_price < typical_price.shift(1), 0)
    pos_mf_sum = pos_mf.rolling(14, min_periods=1).sum()
    neg_mf_sum = neg_mf.rolling(14, min_periods=1).sum().replace(0, 1e-8)
    mfi = 100 - (100 / (1 + pos_mf_sum / neg_mf_sum))
    out["vi_mfi"] = _safe(mfi)

    # --- VWAP deviation ---
    cum_pv = (typical_price * volume).cumsum()
    cum_v = volume.cumsum().replace(0, 1e-8)
    vwap = cum_pv / cum_v
    out["vi_vwap_dev"] = _safe((close - vwap) / vwap.replace(0, 1e-8))

    # --- Volume momentum ---
    vol_ma_5 = volume.rolling(5, min_periods=1).mean()
    vol_ma_20 = volume.rolling(20, min_periods=1).mean().replace(0, 1e-8)
    out["vi_vol_ratio"] = _safe(vol_ma_5 / vol_ma_20)
    out["vi_vol_zscore"] = _zscore(volume, 20)

    # --- Smart vs Dumb money proxy ---
    # Large bars (high volume + directional) = smart money
    vol_rank = volume.rolling(20, min_periods=1).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
    )
    smart_mask = vol_rank > 0.8  # Top 20% volume bars
    smart_ret = ret.where(smart_mask, 0)
    dumb_ret = ret.where(~smart_mask, 0)
    out["vi_smart_money_flow"] = _safe(
        smart_ret.rolling(20, min_periods=1).sum()
        - dumb_ret.rolling(20, min_periods=1).sum()
    )

    # --- Volume-weighted momentum (actual edge over price-only momentum) ---
    vol_weight = volume / volume.rolling(20, min_periods=1).mean().replace(0, 1e-8)
    out["vi_vw_momentum_10"] = _safe(
        (ret * vol_weight).rolling(10, min_periods=1).sum()
    )

    return out


# ==================================================================
# 3. DERIVATIVES DATA
# ==================================================================

def add_derivatives_features(
    df: pd.DataFrame,
    funding_rate: Optional[pd.Series] = None,
    open_interest: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """
    Add derivatives-based features when available.
    Falls back to zero-filled columns when data is not provided.
    """
    out = df.copy()

    if funding_rate is not None and len(funding_rate) > 0:
        # Align to df index
        fr = funding_rate.reindex(out.index, method="ffill").fillna(0)
        out["dr_funding_rate"] = _safe(fr)
        out["dr_funding_zscore"] = _zscore(fr, 20)
        out["dr_funding_momentum"] = _safe(fr.diff(3))
        # Extreme funding = crowded trade = reversal signal
        out["dr_funding_extreme"] = _safe(
            (fr.abs() > fr.rolling(50, min_periods=10).quantile(0.9)).astype(float)
        )
    else:
        for col in ["dr_funding_rate", "dr_funding_zscore",
                     "dr_funding_momentum", "dr_funding_extreme"]:
            out[col] = 0.0

    if open_interest is not None and len(open_interest) > 0:
        oi = open_interest.reindex(out.index, method="ffill").fillna(method="bfill").fillna(0)
        out["dr_oi"] = _safe(oi)
        out["dr_oi_change"] = _safe(oi.pct_change(5))
        out["dr_oi_zscore"] = _zscore(oi, 20)
        # OI increasing + price up = trend confirmation
        # OI increasing + price down = selling pressure
        ret = out["close"].pct_change(5).fillna(0)
        oi_chg = oi.pct_change(5).fillna(0)
        out["dr_oi_price_divergence"] = _safe(
            np.sign(ret) * np.sign(oi_chg) * oi_chg.abs()
        )
    else:
        for col in ["dr_oi", "dr_oi_change", "dr_oi_zscore",
                     "dr_oi_price_divergence"]:
            out[col] = 0.0

    return out


# ==================================================================
# 4. REGIME & STRUCTURE
# ==================================================================

def add_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    """Regime detection features using statistical methods."""
    out = df.copy()
    close = out["close"].astype(float)
    ret = close.pct_change().fillna(0)

    # --- Hurst Exponent (simplified R/S method) ---
    def _hurst(series: pd.Series, max_lag: int = 20) -> float:
        """Estimate Hurst exponent. H < 0.5 = mean-reverting, H > 0.5 = trending."""
        if len(series) < max_lag + 1:
            return 0.5
        lags = range(2, max_lag + 1)
        rs_vals = []
        for lag in lags:
            rs = []
            for start in range(0, len(series) - lag, lag):
                chunk = series.iloc[start:start + lag].values
                mean_c = chunk.mean()
                dev = chunk - mean_c
                cum_dev = np.cumsum(dev)
                r = cum_dev.max() - cum_dev.min()
                s = chunk.std()
                if s > 0:
                    rs.append(r / s)
            if rs:
                rs_vals.append((np.log(lag), np.log(np.mean(rs))))
        if len(rs_vals) < 3:
            return 0.5
        x = np.array([v[0] for v in rs_vals])
        y = np.array([v[1] for v in rs_vals])
        n = len(x)
        slope = (n * (x * y).sum() - x.sum() * y.sum()) / (
            n * (x ** 2).sum() - x.sum() ** 2 + 1e-8
        )
        return float(np.clip(slope, 0, 1))

    out["rg_hurst"] = ret.rolling(100, min_periods=30).apply(
        _hurst, raw=False
    ).fillna(0.5)

    # --- Market Efficiency Ratio (MER) ---
    # MER = net price change / sum of absolute changes
    # High MER = trending, Low MER = noisy/mean-reverting
    for w in [10, 20, 50]:
        net_change = close.diff(w).abs()
        sum_changes = ret.abs().rolling(w, min_periods=1).sum().replace(0, 1e-8)
        out[f"rg_efficiency_{w}"] = _safe(net_change / (sum_changes * close))

    # --- Fractal Dimension Proxy ---
    # Higher = more chaotic, lower = more structured trend
    log_ret_abs = np.log(ret.abs().replace(0, 1e-8))
    out["rg_fractal_20"] = _safe(
        log_ret_abs.rolling(20, min_periods=5).std()
    )

    # --- Cross-Timeframe Momentum Agreement ---
    # Do short and long timeframes agree on direction?
    mom_5 = close.pct_change(5)
    mom_20 = close.pct_change(20)
    mom_50 = close.pct_change(50)
    out["rg_tf_agreement"] = _safe(
        (np.sign(mom_5) + np.sign(mom_20) + np.sign(mom_50)) / 3
    )

    # --- Realized Volatility Term Structure ---
    rv_5 = ret.rolling(5, min_periods=2).std()
    rv_20 = ret.rolling(20, min_periods=5).std().replace(0, 1e-8)
    rv_60 = ret.rolling(60, min_periods=10).std().replace(0, 1e-8)
    out["rg_vol_term_5_20"] = _safe(rv_5 / rv_20)
    out["rg_vol_term_20_60"] = _safe(rv_20 / rv_60)

    # --- Regime Transition Detector ---
    # Sudden change in volatility regime
    vol_ratio = rv_5 / rv_20
    out["rg_vol_regime_change"] = _safe(vol_ratio.diff(3).abs())

    # --- Trend Persistence (autocorrelation of returns) ---
    out["rg_ret_autocorr_1"] = _safe(
        ret.rolling(20, min_periods=5).apply(
            lambda x: x.autocorr(lag=1) if len(x) > 1 else 0, raw=False
        )
    )
    out["rg_ret_autocorr_5"] = _safe(
        ret.rolling(50, min_periods=10).apply(
            lambda x: x.autocorr(lag=5) if len(x) > 5 else 0, raw=False
        )
    )

    return out


# ==================================================================
# 5. STATISTICAL EDGE
# ==================================================================

def add_statistical_features(df: pd.DataFrame) -> pd.DataFrame:
    """Statistical features with proven predictive value."""
    out = df.copy()
    close = out["close"].astype(float)
    ret = close.pct_change().fillna(0)

    # --- Return Distribution Features ---
    for w in [20, 50]:
        out[f"st_skew_{w}"] = _safe(ret.rolling(w, min_periods=5).skew())
        out[f"st_kurt_{w}"] = _safe(ret.rolling(w, min_periods=5).kurt())

    # --- Tail Ratio (upside vs downside tail thickness) ---
    q95 = ret.rolling(50, min_periods=10).quantile(0.95).abs()
    q05 = ret.rolling(50, min_periods=10).quantile(0.05).abs().replace(0, 1e-8)
    out["st_tail_ratio"] = _safe(q95 / q05)

    # --- Downside Deviation ---
    down_ret = ret.where(ret < 0, 0)
    out["st_downside_vol"] = _safe(down_ret.rolling(20, min_periods=3).std())

    # --- Max Drawdown (rolling) ---
    cum_ret = (1 + ret).cumprod()
    roll_max = cum_ret.rolling(50, min_periods=1).max()
    out["st_rolling_dd"] = _safe((cum_ret - roll_max) / roll_max.replace(0, 1e-8))

    # --- Mean Reversion Speed (Ornstein-Uhlenbeck half-life proxy) ---
    price_z = _zscore(close, 20)
    out["st_mean_rev_speed"] = _safe(
        -price_z * ret  # Negative = mean-reverting behavior
    )

    # --- Momentum Quality (Sharpe of recent returns) ---
    for w in [10, 20]:
        mu = ret.rolling(w, min_periods=3).mean()
        sd = ret.rolling(w, min_periods=3).std().replace(0, 1e-8)
        out[f"st_momentum_sharpe_{w}"] = _safe(mu / sd)

    # --- Relative Strength (price vs its moving average) ---
    for w in [10, 20, 50]:
        ma = close.rolling(w, min_periods=1).mean().replace(0, 1e-8)
        out[f"st_rel_strength_{w}"] = _safe((close - ma) / ma)

    return out


# ==================================================================
# MASTER PIPELINE
# ==================================================================

def compute_alpha_features(
    df: pd.DataFrame,
    funding_rate: Optional[pd.Series] = None,
    open_interest: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """
    Compute all alpha features and return enriched DataFrame.

    Args:
        df: OHLCV DataFrame with columns [open, high, low, close, volume]
        funding_rate: Optional funding rate series (aligned to df index)
        open_interest: Optional open interest series (aligned to df index)

    Returns:
        DataFrame with all alpha features added (prefix: of_, vi_, dr_, rg_, st_)
    """
    out = df.copy()

    logger.info("Computing alpha features on %d bars...", len(out))

    out = add_order_flow_features(out)
    out = add_volume_features(out)
    out = add_derivatives_features(out, funding_rate, open_interest)
    out = add_regime_features(out)
    out = add_statistical_features(out)

    # Clean all alpha feature columns
    alpha_cols = [c for c in out.columns if c.startswith(("of_", "vi_", "dr_", "rg_", "st_"))]
    out[alpha_cols] = out[alpha_cols].replace([np.inf, -np.inf], np.nan).fillna(0)

    logger.info("Alpha features computed: %d new columns", len(alpha_cols))

    return out


def get_alpha_feature_names(df: pd.DataFrame) -> List[str]:
    """
    Return list of all alpha feature column names.
    Uses the full feature space (of_, vi_, rg_, st_ prefixed columns)
    to give the model maximum signal diversity.
    """
    alpha_prefixes = ("of_", "vi_", "rg_", "st_")
    return [col for col in df.columns if col.startswith(alpha_prefixes)]
