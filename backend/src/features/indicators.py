"""
Feature engineering for trading: technical indicators and derived features.
All features use past data only (no lookahead).

Includes:
  - Candle structure
  - Volume features & VWAP
  - Momentum & moving averages
  - RSI, MACD, Bollinger Bands
  - ATR, Stochastic Oscillator
  - Returns & volatility
  - Statistical features (z-score, skewness, kurtosis, autocorrelation)
  - Market microstructure features
  - Regime features
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from backend.src.features.advanced_signals import add_institutional_signals
from backend.src.features.alpha_features import compute_alpha_features

# ------------------------------------------------------------------
# Utilities
# ------------------------------------------------------------------


def _safe_divide(a: pd.Series, b: pd.Series, fill: float = 0.0) -> pd.Series:
    with np.errstate(divide="ignore", invalid="ignore"):
        out = a / b
    out = out.replace([np.inf, -np.inf], np.nan).fillna(fill)
    return out


def _clip_finite(
    s: pd.Series, low: Optional[float] = None, high: Optional[float] = None
) -> pd.Series:
    out = s.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    if low is not None:
        out = out.clip(lower=low)
    if high is not None:
        out = out.clip(upper=high)
    return out


class FeatureEngineer:

    def __init__(self, lookback_periods: int = 14):
        self.lookback_periods = lookback_periods

    # ------------------------------------------------
    # Candle structure
    # ------------------------------------------------

    def add_candle_structure(self, df: pd.DataFrame) -> pd.DataFrame:

        df = df.copy()

        o, h, l, c = df["open"], df["high"], df["low"], df["close"]

        df["candle_body"] = c - o
        df["upper_wick"] = h - np.maximum(o, c)
        df["lower_wick"] = np.minimum(o, c) - l
        df["candle_range"] = (h - l).replace(0, 1e-8)

        return df

    # ------------------------------------------------
    # Volume features
    # ------------------------------------------------

    def add_volume_features(self, df: pd.DataFrame, window: int = 20) -> pd.DataFrame:

        df = df.copy()

        v = df["volume"].astype(float).replace(0, np.nan).fillna(1)

        v_ma = v.rolling(window, min_periods=1).mean()

        df["volume_ma"] = v_ma
        df["volume_ratio"] = _safe_divide(v, v_ma, fill=1.0)
        df["volume_momentum"] = v.pct_change(5).fillna(0)

        return df

    # ------------------------------------------------
    # VWAP
    # ------------------------------------------------

    def add_vwap(self, df: pd.DataFrame) -> pd.DataFrame:

        df = df.copy()

        pv = (df["close"] * df["volume"]).cumsum()
        vol = df["volume"].cumsum().replace(0, 1e-8)

        df["VWAP"] = pv / vol

        return df

    # ------------------------------------------------
    # Momentum
    # ------------------------------------------------

    def add_momentum_features(self, df: pd.DataFrame, column="close"):

        df = df.copy()

        p = df[column]

        df["momentum_10"] = p - p.shift(10)
        df["momentum_20"] = p - p.shift(20)

        p10 = p.shift(10).replace(0, 1e-8)

        df["roc"] = _safe_divide(p - p10, p10)

        return df

    # ------------------------------------------------
    # Moving averages
    # ------------------------------------------------

    def add_moving_averages(self, df: pd.DataFrame, column="close"):

        df = df.copy()

        p = df[column]

        df["SMA_7"] = p.rolling(7, min_periods=1).mean()
        df["SMA_21"] = p.rolling(21, min_periods=1).mean()
        df["SMA_50"] = p.rolling(50, min_periods=1).mean()
        df["SMA_200"] = p.rolling(200, min_periods=1).mean()

        df["EMA_12"] = p.ewm(span=12, adjust=False).mean()
        df["EMA_26"] = p.ewm(span=26, adjust=False).mean()
        df["EMA_50"] = p.ewm(span=50, adjust=False).mean()

        return df

    # ------------------------------------------------
    # RSI
    # ------------------------------------------------

    def add_rsi(self, df: pd.DataFrame, column="close"):

        df = df.copy()

        delta = df[column].diff()

        gain = delta.where(delta > 0, 0)
        loss = (-delta).where(delta < 0, 0)

        avg_gain = gain.rolling(self.lookback_periods, min_periods=1).mean()
        avg_loss = loss.rolling(self.lookback_periods, min_periods=1).mean()

        rs = _safe_divide(avg_gain, avg_loss.replace(0, 1e-10))

        df["RSI"] = _clip_finite(100 - (100 / (1 + rs)), 0, 100)

        return df

    # ------------------------------------------------
    # MACD
    # ------------------------------------------------

    def add_macd(self, df: pd.DataFrame, column="close"):

        df = df.copy()

        p = df[column]

        ema_fast = p.ewm(span=12, adjust=False).mean()
        ema_slow = p.ewm(span=26, adjust=False).mean()

        df["MACD"] = ema_fast - ema_slow
        df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()

        df["MACD_hist"] = df["MACD"] - df["MACD_signal"]

        return df

    # ------------------------------------------------
    # Bollinger Bands
    # ------------------------------------------------

    def add_bollinger(self, df: pd.DataFrame, column="close"):

        df = df.copy()

        p = df[column]

        mid = p.rolling(20, min_periods=1).mean()
        std = p.rolling(20, min_periods=1).std().replace(0, 1e-8)

        df["BB_mid"] = mid
        df["BB_upper"] = mid + 2 * std
        df["BB_lower"] = mid - 2 * std

        df["BB_width"] = _safe_divide(df["BB_upper"] - df["BB_lower"], mid)

        # BB %B — position within bands
        df["BB_pctb"] = _safe_divide(
            p - df["BB_lower"], df["BB_upper"] - df["BB_lower"], fill=0.5
        )

        return df

    # ------------------------------------------------
    # ATR (Average True Range) — NEW
    # ------------------------------------------------

    def add_atr(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:

        df = df.copy()

        h, l, c = df["high"], df["low"], df["close"]

        prev_close = c.shift(1)

        tr1 = h - l
        tr2 = (h - prev_close).abs()
        tr3 = (l - prev_close).abs()

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        df["true_range"] = true_range
        df["ATR"] = true_range.rolling(period, min_periods=1).mean()
        df["atr_14"] = df["ATR"]  # Alias for backward compatibility

        # Normalized ATR (% of price)
        df["ATR_pct"] = _safe_divide(df["ATR"], c, fill=0.0)

        return df

    # ------------------------------------------------
    # Stochastic Oscillator — NEW
    # ------------------------------------------------

    def add_stochastic(
        self, df: pd.DataFrame, k_period: int = 14, d_period: int = 3
    ) -> pd.DataFrame:

        df = df.copy()

        h_high = df["high"].rolling(k_period, min_periods=1).max()
        l_low = df["low"].rolling(k_period, min_periods=1).min()

        denom = (h_high - l_low).replace(0, 1e-8)

        df["STOCH_K"] = _clip_finite(((df["close"] - l_low) / denom) * 100, 0, 100)
        df["STOCH_D"] = df["STOCH_K"].rolling(d_period, min_periods=1).mean()

        return df

    # ------------------------------------------------
    # Returns & Volatility
    # ------------------------------------------------

    def add_returns(self, df: pd.DataFrame, column="close"):

        df = df.copy()

        p = df[column]

        df["returns"] = p.pct_change().fillna(0)

        prev = p.shift(1).replace(0, 1e-8)

        df["log_returns"] = np.log(p / prev).fillna(0)

        df["volatility_20"] = df["returns"].rolling(20, min_periods=1).std()
        df["volatility_60"] = df["returns"].rolling(60, min_periods=1).std()

        return df

    # ------------------------------------------------
    # Statistical Features — NEW
    # ------------------------------------------------

    def add_statistical_features(
        self, df: pd.DataFrame, window: int = 20
    ) -> pd.DataFrame:

        df = df.copy()

        ret = (
            df["returns"]
            if "returns" in df.columns
            else df["close"].pct_change().fillna(0)
        )

        # Rolling z-score of returns
        r_mean = ret.rolling(window, min_periods=1).mean()
        r_std = ret.rolling(window, min_periods=1).std().replace(0, 1e-8)
        df["z_score"] = (ret - r_mean) / r_std

        # Price z-score (deviation from rolling mean)
        p = df["close"]
        p_mean = p.rolling(window, min_periods=1).mean()
        p_std = p.rolling(window, min_periods=1).std().replace(0, 1e-8)
        df["price_z_score"] = (p - p_mean) / p_std

        # Rolling skewness
        df["skewness"] = ret.rolling(window, min_periods=3).skew().fillna(0)

        # Rolling kurtosis
        df["kurtosis"] = ret.rolling(window, min_periods=4).kurt().fillna(0)

        # Autocorrelation (lags 1-5)
        for lag in [1, 2, 5]:
            df[f"autocorr_lag{lag}"] = (
                ret.rolling(window, min_periods=lag + 1)
                .apply(lambda x, l=lag: x.autocorr(lag=l) if len(x) >= (l + 2) else 0.0, raw=False)
                .fillna(0)
            )

        # Volatility of volatility (vol clustering)
        if "volatility_20" in df.columns:
            vol = df["volatility_20"]
        else:
            vol = ret.rolling(20, min_periods=1).std()
        df["vol_of_vol"] = vol.rolling(window, min_periods=1).std().fillna(0)

        # Hurst exponent proxy (mean-reverting < 0.5, trending > 0.5)
        df["returns_abs_mean"] = ret.abs().rolling(window, min_periods=1).mean()
        df["returns_std_ratio"] = _safe_divide(
            ret.rolling(window, min_periods=1).std(),
            ret.abs().rolling(window, min_periods=1).mean(),
            fill=1.0,
        )

        return df

    # ------------------------------------------------
    # Market Microstructure Features — NEW
    # ------------------------------------------------

    def add_microstructure_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Proxy microstructure features from OHLCV data.
        True microstructure requires tick/order book data.
        """
        df = df.copy()

        h, l, c, o, v = df["high"], df["low"], df["close"], df["open"], df["volume"]

        # Bid-ask spread proxy (Corwin-Schultz estimator from high-low)
        # S = 2(e^alpha - 1) / (1 + e^alpha)
        log_hl = np.log(h / l.replace(0, 1e-8))
        log_hl_sq = log_hl**2
        beta = log_hl_sq + log_hl_sq.shift(1)
        gamma = (
            np.log(
                df[["high"]].rolling(2, min_periods=1).max().values.flatten()
                / df[["low"]].rolling(2, min_periods=1).min().values.flatten()
            )
            ** 2
        )

        gamma_s = pd.Series(gamma, index=df.index)
        alpha_raw = (np.sqrt(2 * beta) - np.sqrt(beta)) / (
            3 - 2 * np.sqrt(2)
        ) - np.sqrt(gamma_s / (3 - 2 * np.sqrt(2)))
        alpha_raw = alpha_raw.replace([np.inf, -np.inf], np.nan).fillna(0)
        df["spread_proxy"] = (
            (2 * (np.exp(alpha_raw) - 1) / (1 + np.exp(alpha_raw)))
            .clip(0, 0.1)
            .fillna(0)
        )

        # Order flow imbalance proxy (close position within bar)
        df["close_position"] = _safe_divide(c - l, (h - l).replace(0, 1e-8), fill=0.5)

        # Buy volume proxy (proportion of bar in upper half)
        df["buy_volume_proxy"] = df["close_position"] * v

        # Trade flow imbalance (change in buy volume proportion)
        df["trade_flow_imbalance"] = df["close_position"].diff().fillna(0)

        # Liquidity proxy (volume / range = tighter means more liquid)
        df["liquidity_proxy"] = _safe_divide(v, (h - l).replace(0, 1e-8))
        # Normalize
        liq_mean = df["liquidity_proxy"].rolling(20, min_periods=1).mean()
        df["liquidity_ratio"] = _safe_divide(df["liquidity_proxy"], liq_mean, fill=1.0)

        # Amihud illiquidity measure (|return| / volume)
        if "returns" in df.columns:
            df["amihud_illiquidity"] = _safe_divide(
                df["returns"].abs(), v.replace(0, 1e-8)
            )
        else:
            df["amihud_illiquidity"] = _safe_divide(
                c.pct_change().abs(), v.replace(0, 1e-8)
            )

        return df

    # ------------------------------------------------
    # Regime Features — Enhanced
    # ------------------------------------------------

    def add_regime_features(self, df: pd.DataFrame):

        df = df.copy()

        price = df["close"].replace(0, 1e-8)

        # Trend strength (EMA spread)
        df["trend_strength"] = (df["EMA_12"] - df["EMA_26"]) / price

        # Volatility regime
        vol = (
            df["volatility_20"]
            if "volatility_20" in df.columns
            else df["close"].pct_change().rolling(20).std()
        )
        vol_med = vol.rolling(20, min_periods=1).median()
        df["volatility_regime"] = (vol > vol_med).astype(int)

        # ADX-like trend indicator (simplified from directional movement)
        plus_dm = df["high"].diff()
        minus_dm = -df["low"].diff()

        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

        atr = (
            df["ATR"]
            if "ATR" in df.columns
            else (df["high"] - df["low"]).rolling(14, min_periods=1).mean()
        )

        plus_di = _safe_divide(plus_dm.rolling(14, min_periods=1).mean(), atr) * 100
        minus_di = _safe_divide(minus_dm.rolling(14, min_periods=1).mean(), atr) * 100

        dx = (
            _safe_divide(
                (plus_di - minus_di).abs(), (plus_di + minus_di).replace(0, 1e-8)
            )
            * 100
        )
        df["ADX"] = _clip_finite(dx.rolling(14, min_periods=1).mean(), 0, 100)

        # Momentum regime: positive vs negative rolling returns
        ret_20 = df["close"].pct_change(20).fillna(0)
        df["momentum_regime"] = (ret_20 > 0).astype(int)

        # Risk-on / Risk-off proxy (vol-adjusted momentum)
        vol_safe = vol.replace(0, 1e-8)
        df["risk_regime_score"] = _safe_divide(ret_20, vol_safe)

        return df

    # ------------------------------------------------
    # Multi-Horizon Targets
    # ------------------------------------------------

    def add_multi_horizon_targets(
        self, df: pd.DataFrame, column="close", horizons=None
    ) -> pd.DataFrame:
        """Add direction targets for multiple horizons."""
        df = df.copy()

        if horizons is None:
            horizons = [1, 3, 5, 10, 20]

        p = df[column]

        for h in horizons:
            forward = p.pct_change(h).shift(-h)
            df[f"Target_{h}"] = forward
            df[f"Target_Dir_{h}"] = (forward > 0).astype(int)

        return df

    # ------------------------------------------------
    # Target
    # ------------------------------------------------

    def add_target(
        self,
        df: pd.DataFrame,
        column="close",
        horizon=5,
        threshold_bps=25,
    ):
        """
        Add target labels with transaction-cost-aware thresholds.

        Args:
            column: price column
            horizon: forward-looking bars
            threshold_bps: minimum return (in basis points) to label as
                           directional. Returns within [-threshold, +threshold]
                           are labeled 0 (no-trade / noise zone).
        """
        df = df.copy()

        p = df[column]
        forward = p.pct_change(horizon).shift(-horizon)

        df["Target"] = forward

        threshold = threshold_bps / 10_000  # Convert bps to decimal

        # Binary target for classification:
        #   1 = forward return > +threshold (bullish)
        #   0 = forward return < -threshold (bearish) OR noise zone
        #
        # The key insight: the model learns P(bullish) = P(return > threshold).
        # Noise zone bars (returns within [-threshold, +threshold]) are labeled
        # 0 but down-weighted via Target_Actionable during training.
        # This forces the model to output ~0.5 for ambiguous bars, which is
        # exactly the regime where StrategyEngine correctly produces no signal.
        df["Target_Direction"] = (forward > threshold).astype(int)

        # Actionable flag: True for clear directional moves, False for noise
        # Used for sample weighting during training (2x weight on actionable)
        df["Target_Actionable"] = (
            (forward > threshold) | (forward < -threshold)
        ).astype(int)

        return df

    # ------------------------------------------------
    # Full Pipeline
    # ------------------------------------------------

    def transform(
        self, df: pd.DataFrame, column="close", add_target=True, target_horizon=5
    ):

        df = df.copy()

        # Core candle structure
        df = self.add_candle_structure(df)
        df = self.add_volume_features(df)
        df = self.add_vwap(df)

        # Technical indicators
        df = self.add_momentum_features(df)
        df = self.add_moving_averages(df)
        df = self.add_rsi(df)
        df = self.add_macd(df)
        df = self.add_bollinger(df)
        df = self.add_atr(df)
        df = self.add_stochastic(df)

        # Returns and volatility
        df = self.add_returns(df)

        # Statistical features
        df = self.add_statistical_features(df)

        # Market microstructure
        df = self.add_microstructure_features(df)

        # Regime features (depends on EMAs, volatility, ATR)
        df = self.add_regime_features(df)

        # Institutional multi-factor alpha extension (20+ additional signals)
        df = add_institutional_signals(df)

        # NEW: Research-grade alpha features (order flow, volume, regime, stats)
        df = compute_alpha_features(df)

        # Target
        if add_target:
            df = self.add_target(df, column, target_horizon)

        # Clean up
        exclude = {"Target", "Target_Direction", "Target_Actionable"}
        features = [c for c in df.columns if c not in exclude]
        df[features] = df[features].replace([np.inf, -np.inf], np.nan).fillna(0)
        df = df.sort_index()

        return df

    # ------------------------------------------------
    # Alias
    # ------------------------------------------------

    def add_all_indicators(self, df, column="close", add_target=True, target_horizon=5):
        return self.transform(df, column, add_target, target_horizon)
