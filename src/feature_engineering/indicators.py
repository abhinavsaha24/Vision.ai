"""
Feature engineering for trading: technical indicators and derived features.
All features use past data only (no lookahead).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import List, Optional


def _safe_divide(a: pd.Series, b: pd.Series, fill: float = 0.0) -> pd.Series:
    with np.errstate(divide="ignore", invalid="ignore"):
        out = a / b
    out = out.replace([np.inf, -np.inf], np.nan).fillna(fill)
    return out


def _clip_finite(s: pd.Series, low: Optional[float] = None, high: Optional[float] = None) -> pd.Series:
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

        df["EMA_12"] = p.ewm(span=12, adjust=False).mean()
        df["EMA_26"] = p.ewm(span=26, adjust=False).mean()

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

        return df


    # ------------------------------------------------
    # Returns
    # ------------------------------------------------

    def add_returns(self, df: pd.DataFrame, column="close"):

        df = df.copy()

        p = df[column]

        df["returns"] = p.pct_change().fillna(0)

        prev = p.shift(1).replace(0, 1e-8)

        df["log_returns"] = np.log(p / prev).fillna(0)

        df["volatility_20"] = df["returns"].rolling(20, min_periods=1).std()

        return df


    # ------------------------------------------------
    # Regime detection
    # ------------------------------------------------

    def add_regime_features(self, df: pd.DataFrame):

        df = df.copy()

        price = df["close"].replace(0, 1e-8)

        df["trend_strength"] = (df["EMA_12"] - df["EMA_26"]) / price

        vol = df["volatility_20"]

        vol_med = vol.rolling(20, min_periods=1).median()

        df["volatility_regime"] = (vol > vol_med).astype(int)

        return df


    # ------------------------------------------------
    # Target
    # ------------------------------------------------

    def add_target(self, df: pd.DataFrame, column="close", horizon=5):

        df = df.copy()

        p = df[column]

        forward = p.pct_change(horizon).shift(-horizon)

        df["Target"] = forward
        df["Target_Direction"] = (forward > 0).astype(int)

        return df


    # ------------------------------------------------
    # Pipeline
    # ------------------------------------------------

    def transform(self, df: pd.DataFrame, column="close", add_target=True, target_horizon=5):

        df = df.copy()

        df = self.add_candle_structure(df)
        df = self.add_volume_features(df)

        df = self.add_vwap(df)

        df = self.add_momentum_features(df)
        df = self.add_moving_averages(df)

        df = self.add_rsi(df)
        df = self.add_macd(df)

        df = self.add_bollinger(df)

        df = self.add_returns(df)

        df = self.add_regime_features(df)

        if add_target:
            df = self.add_target(df, column, target_horizon)

        exclude = {"Target", "Target_Direction"}

        features = [c for c in df.columns if c not in exclude]

        df[features] = df[features].replace([np.inf, -np.inf], np.nan).fillna(0)

        df = df.sort_index()

        return df


    # ------------------------------------------------
    # Alias
    # ------------------------------------------------

    def add_all_indicators(self, df, column="close", add_target=True, target_horizon=5):

        return self.transform(df, column, add_target, target_horizon)