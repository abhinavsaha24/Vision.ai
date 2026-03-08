"""
Feature engineering for trading: technical indicators and derived features.

All features are computed using only past data (no lookahead) to avoid data leakage.
Numerical stability: inf/nan handled via safe division and fillna(0) where appropriate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import List, Optional


def _safe_divide(a: pd.Series, b: pd.Series, fill: float = 0.0) -> pd.Series:
    """Element-wise a/b, replacing inf/nan with fill."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out = a / b
    out = out.replace([np.inf, -np.inf], np.nan).fillna(fill)
    return out


def _clip_finite(s: pd.Series, low: Optional[float] = None, high: Optional[float] = None) -> pd.Series:
    """Clip to [low, high] and replace remaining nan/inf with 0."""
    out = s.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    if low is not None:
        out = out.clip(lower=low)
    if high is not None:
        out = out.clip(upper=high)
    return out


class FeatureEngineer:
    """
    Builds technical and structural features for ML models.
    All methods use only past data (rolling/ewm with current bar included, no future bars).
    """

    def __init__(self, lookback_periods: int = 14) -> None:
        self.lookback_periods = lookback_periods

    def add_candle_structure(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Candle structure features (past-only): body, upper wick, lower wick, range.
        Uses open, high, low, close (column names lower case).
        """
        df = df.copy()
        o, h, l, c = df["open"], df["high"], df["low"], df["close"]
        df["candle_body"] = (c - o).astype(float)
        df["upper_wick"] = (h - np.maximum(o, c)).astype(float)
        df["lower_wick"] = (np.minimum(o, c) - l).astype(float)
        df["candle_range"] = (h - l).astype(float)
        # Avoid zeros where range is 0
        df["candle_range"] = df["candle_range"].replace(0, np.nan).fillna(1e-8)
        return df

    def add_volume_features(self, df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
        """Volume features: moving average, ratio to MA, momentum (past-only)."""
        df = df.copy()
        v = df["volume"].astype(float).replace(0, np.nan).fillna(1.0)
        v_ma = v.rolling(window=window, min_periods=1).mean()
        df["volume_moving_average"] = v_ma
        df["volume_ratio"] = _safe_divide(v, v_ma, fill=1.0)
        df["volume_momentum"] = v.pct_change(periods=5).fillna(0).replace([np.inf, -np.inf], 0)
        return df

    def add_momentum_features(self, df: pd.DataFrame, column: str = "close") -> pd.DataFrame:
        """Momentum: momentum_10, momentum_20, price_rate_of_change (past-only)."""
        df = df.copy()
        p = df[column].astype(float)
        df["momentum_10"] = (p - p.shift(10)).fillna(0)
        df["momentum_20"] = (p - p.shift(20)).fillna(0)
        # ROC: (price - price_n_ago) / price_n_ago; avoid div by zero
        p_10 = p.shift(10).replace(0, np.nan).fillna(1e-8)
        df["price_rate_of_change"] = _safe_divide(p - p_10, p_10, fill=0)
        return df

    def add_trend_slope_features(self, df: pd.DataFrame, column: str = "close") -> pd.DataFrame:
        """Trend slopes: ema_slope and sma_slope (change over 5 bars, past-only)."""
        df = df.copy()
        p = df[column].astype(float)
        ema = p.ewm(span=12, adjust=False).mean()
        sma = p.rolling(window=20, min_periods=1).mean()
        df["ema_slope"] = (ema - ema.shift(5)).fillna(0)
        df["sma_slope"] = (sma - sma.shift(5)).fillna(0)
        return df

    def add_moving_averages(self, df: pd.DataFrame, column: str = "close") -> pd.DataFrame:
        """Simple and exponential moving averages (past-only)."""
        df = df.copy()
        p = df[column].astype(float)
        df["SMA_7"] = p.rolling(window=7, min_periods=1).mean()
        df["SMA_21"] = p.rolling(window=21, min_periods=1).mean()
        df["SMA_50"] = p.rolling(window=50, min_periods=1).mean()
        df["EMA_12"] = p.ewm(span=12, adjust=False).mean()
        df["EMA_26"] = p.ewm(span=26, adjust=False).mean()
        return df

    def add_rsi(self, df: pd.DataFrame, column: str = "close") -> pd.DataFrame:
        """Relative Strength Index (past-only). Bounded and NaN-safe."""
        df = df.copy()
        delta = df[column].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.rolling(window=self.lookback_periods, min_periods=1).mean()
        avg_loss = loss.rolling(window=self.lookback_periods, min_periods=1).mean()
        rs = _safe_divide(avg_gain, avg_loss.replace(0, np.nan).fillna(1e-10), fill=0)
        df["RSI"] = _clip_finite(100 - (100 / (1 + rs)), 0, 100)
        return df

    def add_macd(
        self,
        df: pd.DataFrame,
        column: str = "close",
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> pd.DataFrame:
        """MACD, signal line, histogram (past-only)."""
        df = df.copy()
        p = df[column].astype(float)
        ema_fast = p.ewm(span=fast, adjust=False).mean()
        ema_slow = p.ewm(span=slow, adjust=False).mean()
        df["MACD"] = (ema_fast - ema_slow).fillna(0)
        df["MACD_Signal"] = df["MACD"].ewm(span=signal, adjust=False).mean().fillna(0)
        df["MACD_Histogram"] = (df["MACD"] - df["MACD_Signal"]).fillna(0)
        return df

    def add_bollinger_bands(
        self,
        df: pd.DataFrame,
        column: str = "close",
        std_dev: float = 2.0,
        window: int = 20,
    ) -> pd.DataFrame:
        """Bollinger Bands; width is normalized and NaN-safe."""
        df = df.copy()
        p = df[column].astype(float)
        mid = p.rolling(window=window, min_periods=1).mean()
        std = p.rolling(window=window, min_periods=1).std().fillna(0).replace(0, 1e-8)
        df["BB_Middle"] = mid
        df["BB_Upper"] = mid + std * std_dev
        df["BB_Lower"] = mid - std * std_dev
        df["BB_Width"] = _safe_divide(
            df["BB_Upper"] - df["BB_Lower"],
            mid.replace(0, np.nan).fillna(1e-8),
            fill=0,
        )
        return df

    def add_returns(self, df: pd.DataFrame, column: str = "close") -> pd.DataFrame:
        """Returns and volatility (past-only)."""
        df = df.copy()
        p = df[column].astype(float)
        df["Returns"] = p.pct_change().fillna(0).replace([np.inf, -np.inf], 0)
        prev = p.shift(1).replace(0, np.nan).fillna(p.iloc[0] if len(p) else 1e-8)
        df["Log_Returns"] = np.log(p / prev).fillna(0).replace([np.inf, -np.inf], 0)
        df["Volatility_20"] = (
            df["Returns"]
            .rolling(window=20, min_periods=1)
            .std()
            .fillna(0)
            .replace([np.inf, -np.inf], 0)
        )
        return df

    def add_lagged_returns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Lagged return features (past-only): returns_lag_1, 3, 5, 10.
        Requires 'Returns' column; uses shift so only past data.
        """
        df = df.copy()
        if "Returns" not in df.columns:
            raise ValueError("add_lagged_returns requires 'Returns'; call add_returns first.")
        r = df["Returns"].astype(float)
        for lag in (1, 3, 5, 10):
            s = r.shift(lag).fillna(0).replace([np.inf, -np.inf], 0)
            df[f"returns_lag_{lag}"] = s
        return df

    def add_statistical_features(
        self, df: pd.DataFrame, window: int = 20
    ) -> pd.DataFrame:
        """
        Rolling skewness, kurtosis, and z-score of returns (past-only).
        Requires 'Returns'. Numerically stable: inf/nan filled with 0.
        """
        df = df.copy()
        if "Returns" not in df.columns:
            raise ValueError("add_statistical_features requires 'Returns'; call add_returns first.")
        r = df["Returns"].astype(float)
        # Rolling skewness and kurtosis (can be NaN for small samples)
        df["rolling_skewness_20"] = (
            r.rolling(window=window, min_periods=2)
            .skew()
            .fillna(0)
            .replace([np.inf, -np.inf], 0)
        )
        df["rolling_kurtosis_20"] = (
            r.rolling(window=window, min_periods=4)
            .kurt()
            .fillna(0)
            .replace([np.inf, -np.inf], 0)
        )
        # Rolling z-score: (r - rolling_mean) / rolling_std
        r_mean = r.rolling(window=window, min_periods=1).mean()
        r_std = r.rolling(window=window, min_periods=1).std().replace(0, np.nan).fillna(1e-8)
        df["rolling_zscore_returns"] = _safe_divide(r - r_mean, r_std, fill=0)
        df["rolling_zscore_returns"] = _clip_finite(
            df["rolling_zscore_returns"], low=-10.0, high=10.0
        )
        return df

    def add_volatility_indicators(
        self,
        df: pd.DataFrame,
        column: str = "close",
        atr_window: int = 14,
        short_vol_window: int = 5,
        long_vol_window: int = 20,
    ) -> pd.DataFrame:
        """
        ATR, realized volatility, and volatility ratio (past-only).
        ATR uses high, low, close; realized vol = rolling std of returns.
        """
        df = df.copy()
        h, l, c = df["high"].astype(float), df["low"].astype(float), df[column].astype(float)
        prev_close = c.shift(1).fillna(c.iloc[0] if len(c) else 1e-8)
        tr = np.maximum(h - l, np.maximum((h - prev_close).abs(), (l - prev_close).abs()))
        df["ATR"] = (
            tr.rolling(window=atr_window, min_periods=1)
            .mean()
            .fillna(0)
            .replace([np.inf, -np.inf], 0)
        )
        if "Returns" not in df.columns:
            raise ValueError("add_volatility_indicators expects 'Returns'; call add_returns first.")
        r = df["Returns"].astype(float)
        df["realized_volatility"] = (
            r.rolling(window=long_vol_window, min_periods=1)
            .std()
            .fillna(0)
            .replace([np.inf, -np.inf], 0)
        )
        short_vol = (
            r.rolling(window=short_vol_window, min_periods=1)
            .std()
            .replace(0, np.nan)
            .fillna(1e-8)
        )
        long_vol = (
            r.rolling(window=long_vol_window, min_periods=1)
            .std()
            .replace(0, np.nan)
            .fillna(1e-8)
        )
        df["volatility_ratio"] = _safe_divide(short_vol, long_vol, fill=1.0)
        df["volatility_ratio"] = _clip_finite(df["volatility_ratio"], low=0.0, high=10.0)
        return df

    def add_calendar_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calendar features from index (past-only): hour_of_day, day_of_week, weekend.
        Index must be datetime-like. For daily data hour is often 0.
        """
        df = df.copy()
        if not pd.api.types.is_datetime64_any_dtype(df.index):
            df["hour_of_day"] = 0
            df["day_of_week"] = 0
            df["weekend"] = 0
            return df
        df["hour_of_day"] = df.index.hour
        df["day_of_week"] = df.index.dayofweek  # 0=Monday, 6=Sunday
        df["weekend"] = (df.index.dayofweek >= 5).astype(np.int64)
        return df

    def add_regime_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Regime detection (past-only): trend_strength = EMA_12 - EMA_26,
        volatility_regime = 1 if current vol > rolling median vol else 0.
        Requires EMA_12, EMA_26 and a volatility column (e.g. realized_volatility or Volatility_20).
        """
        df = df.copy()
        if "EMA_12" not in df.columns or "EMA_26" not in df.columns:
            raise ValueError("add_regime_features requires EMA_12 and EMA_26; call add_moving_averages first.")
        df["trend_strength"] = (df["EMA_12"] - df["EMA_26"]).fillna(0).replace([np.inf, -np.inf], 0)
        vol_col = "realized_volatility" if "realized_volatility" in df.columns else "Volatility_20"
        vol = df[vol_col].astype(float)
        vol_median = vol.rolling(window=20, min_periods=1).median()
        df["volatility_regime"] = (vol > vol_median).astype(np.int64)
        return df

    def add_target(self, df: pd.DataFrame, column: str = "close", horizon: int = 5) -> pd.DataFrame:
        """
        Target for classification: forward return direction (1 = up, 0 = down).
        Uses future data only for the label; last `horizon` rows will have NaN target and are dropped later.
        """
        df = df.copy()
        p = df[column].astype(float)
        forward_ret = p.pct_change(horizon).shift(-horizon)
        df["Target"] = forward_ret
        df["Target_Direction"] = (forward_ret > 0).astype(float)
        # Rows with NaN target are excluded at split time (no use in training)
        return df

    def transform(
        self,
        df: pd.DataFrame,
        column: str = "close",
        add_target: bool = True,
        target_horizon: int = 5,
    ) -> pd.DataFrame:
        """
        Apply all feature steps in order (past-only features first, then target).
        Returns DataFrame with NaN in target for last `target_horizon` rows; caller should dropna or split accordingly.
        """
        df = df.copy()
        df = self.add_candle_structure(df)
        df = self.add_volume_features(df)
        df = self.add_momentum_features(df, column)
        df = self.add_trend_slope_features(df, column)
        df = self.add_moving_averages(df, column)
        df = self.add_rsi(df, column)
        df = self.add_macd(df, column)
        df = self.add_bollinger_bands(df, column)
        df = self.add_returns(df, column)
        df = self.add_lagged_returns(df)
        df = self.add_statistical_features(df)
        df = self.add_volatility_indicators(df, column=column)
        df = self.add_calendar_features(df)
        df = self.add_regime_features(df)
        if add_target:
            df = self.add_target(df, column, target_horizon)
        # Fill any remaining NaN in feature columns with 0 (target may stay NaN)
        feature_cols = [c for c in df.columns if c not in ("Target", "Target_Direction")]
        df[feature_cols] = df[feature_cols].fillna(0).replace([np.inf, -np.inf], 0)
        return df

    def normalize_features(
        self,
        df: pd.DataFrame,
        columns: Optional[List[str]] = None,
        method: str = "rolling_zscore",
        window: int = 20,
    ) -> pd.DataFrame:
        """
        Optional normalization for neural networks (past-only, no lookahead).

        Uses only past data: rolling or expanding mean/std so each row is
        normalized with statistics from current and prior rows only.

        Args:
            df: DataFrame with feature columns.
            columns: Columns to normalize. If None, all numeric columns except
                     'Target' and 'Target_Direction' are normalized.
            method: 'rolling_zscore' (rolling mean/std) or 'expanding_zscore'
                    (expanding mean/std from start). Both are past-only.
            window: Rolling window size when method='rolling_zscore'.

        Returns:
            DataFrame with selected columns normalized; inf/nan set to 0.
        """
        df = df.copy()
        exclude = {"Target", "Target_Direction"}
        if columns is None:
            columns = [
                c for c in df.select_dtypes(include=[np.number]).columns
                if c not in exclude
            ]
        for col in columns:
            if col not in df.columns:
                continue
            s = df[col].astype(float)
            if method == "rolling_zscore":
                m = s.rolling(window=window, min_periods=1).mean()
                std = s.rolling(window=window, min_periods=1).std().replace(0, np.nan).fillna(1e-8)
            else:  # expanding_zscore
                m = s.expanding(min_periods=1).mean()
                std = s.expanding(min_periods=1).std().replace(0, np.nan).fillna(1e-8)
            out = _safe_divide(s - m, std, fill=0)
            df[col] = _clip_finite(out, low=-10.0, high=10.0)
        return df

    def add_all_indicators(
        self,
        df: pd.DataFrame,
        column: str = "close",
        add_target: bool = True,
        target_horizon: int = 5,
    ) -> pd.DataFrame:
        """Alias for transform."""
        return self.transform(df, column, add_target, target_horizon)
