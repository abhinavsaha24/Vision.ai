"""
Mean reversion strategy — research-backed implementation.

Based on: Ornstein-Uhlenbeck mean-reverting process

Mathematical model:
  dY_t = κ(θ - Y_t)dt + σdW_t

Trading logic:
  z_t = (X_t - μ_t) / σ_t
  Short when z_t > z_entry, Long when z_t < -z_entry
  Exit when |z_t| < z_exit

Features:
  - Multi-indicator z-score (price, RSI, Bollinger)
  - Configurable entry/exit thresholds
  - Half-life awareness for position sizing
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class MeanReversionStrategy:
    """
    Z-score based mean reversion strategy.

    Trades against extreme deviations from the rolling mean,
    expecting prices to revert toward equilibrium.

    Parameters:
        z_entry: z-score threshold for entry (default 2.0)
        z_exit: z-score threshold for exit (default 0.3)
        lookback: rolling window for mean/std calculation
        use_rsi: also incorporate RSI-based mean reversion
        rsi_oversold: RSI level considered oversold
        rsi_overbought: RSI level considered overbought
    """

    def __init__(
        self,
        z_entry: float = 2.0,
        z_exit: float = 0.3,
        lookback: int = 20,
        use_rsi: bool = True,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
    ):
        self.z_entry = z_entry
        self.z_exit = z_exit
        self.lookback = lookback
        self.use_rsi = use_rsi
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought

    def generate_signal(self, df: pd.DataFrame = None, **kwargs) -> int:
        """
        Generate mean reversion signal.

        Combines z-score of price vs rolling mean with optional RSI
        and Bollinger Band confirmation.
        """
        if df is None or "close" not in df.columns:
            return 0
        if len(df) < self.lookback + 1:
            return 0

        try:
            close = df["close"]
            signals = []

            # --- Signal 1: Z-score of price vs rolling mean ---
            rolling_mean = close.rolling(self.lookback).mean()
            rolling_std = close.rolling(self.lookback).std()

            current_z = 0.0
            if rolling_std.iloc[-1] > 0:
                current_z = (close.iloc[-1] - rolling_mean.iloc[-1]) / rolling_std.iloc[
                    -1
                ]

            if current_z > self.z_entry:
                signals.append(-1)  # overbought → short
            elif current_z < -self.z_entry:
                signals.append(1)  # oversold → long
            elif abs(current_z) < self.z_exit:
                signals.append(0)  # near mean → neutral
            else:
                signals.append(0)

            # --- Signal 2: RSI mean reversion ---
            if self.use_rsi and "RSI" in df.columns:
                rsi = df["RSI"].iloc[-1]
                if rsi < self.rsi_oversold:
                    signals.append(1)  # oversold → long
                elif rsi > self.rsi_overbought:
                    signals.append(-1)  # overbought → short
                else:
                    signals.append(0)

            # --- Signal 3: Bollinger Band reversion ---
            if "BB_upper" in df.columns and "BB_lower" in df.columns:
                price = close.iloc[-1]
                bb_upper = df["BB_upper"].iloc[-1]
                bb_lower = df["BB_lower"].iloc[-1]

                if price > bb_upper:
                    signals.append(-1)  # above upper band → short
                elif price < bb_lower:
                    signals.append(1)  # below lower band → long
                else:
                    signals.append(0)

            # --- Combine signals ---
            if not signals:
                return 0

            avg_signal = np.mean(signals)

            if avg_signal > 0.3:
                return 1
            elif avg_signal < -0.3:
                return -1
            return 0

        except Exception as e:
            logger.error("MeanReversionStrategy error: %s", e)
            return 0

    def compute_half_life(self, series: pd.Series) -> float:
        """
        Compute Ornstein-Uhlenbeck half-life of mean reversion.

        dS = θ(μ - S)dt + σdW
        half_life = -ln(2) / θ

        Estimated via OLS: ΔS_t = θ·S_{t-1} + c
        """
        if len(series) < 10:
            return float("inf")

        try:
            lag = series.shift(1).dropna()
            delta = series.diff().dropna()
            min_len = min(len(lag), len(delta))
            if min_len < 2:
                return float("inf")
            lag = lag.iloc[-min_len:]
            delta = delta.iloc[-min_len:]

            x = lag.values
            y = delta.values

            var_x = np.var(x)
            if not np.isfinite(var_x) or var_x <= 1e-12:
                return float("inf")

            theta = np.cov(x, y)[0, 1] / var_x

            if theta >= 0:
                return float("inf")  # not mean-reverting

            return -np.log(2) / theta

        except Exception:
            return float("inf")
