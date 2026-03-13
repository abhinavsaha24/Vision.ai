"""
Volatility-based trading strategies.

Strategies:
  - VolatilityBreakoutStrategy: ATR-scaled breakout detection
  - VolatilityCompressionStrategy: Bollinger squeeze → expansion
"""

from __future__ import annotations

import pandas as pd
import numpy as np


class VolatilityBreakoutStrategy:
    """ATR-based volatility breakout strategy."""

    def __init__(self, atr_multiplier: float = 1.5):
        self.atr_multiplier = atr_multiplier

    def generate_signal(self, df: pd.DataFrame) -> int:
        if "ATR" not in df.columns or len(df) < 2:
            return 0

        close = df["close"].iloc[-1]
        prev_close = df["close"].iloc[-2]
        atr = df["ATR"].iloc[-1]

        if atr <= 0:
            return 0

        move = close - prev_close

        if move > atr * self.atr_multiplier:
            return 1  # volatility breakout up
        if move < -atr * self.atr_multiplier:
            return -1  # volatility breakout down

        return 0


class VolatilityCompressionStrategy:
    """Bollinger Band squeeze detection — low vol precedes big moves."""

    def __init__(self, squeeze_threshold: float = 0.02, lookback: int = 20):
        self.squeeze_threshold = squeeze_threshold
        self.lookback = lookback

    def generate_signal(self, df: pd.DataFrame) -> int:
        if "BB_width" not in df.columns or len(df) < self.lookback + 1:
            return 0

        bb_width = df["BB_width"]

        # Current width vs recent minimum
        current_width = bb_width.iloc[-1]
        recent_min_width = bb_width.iloc[-self.lookback:].min()

        # Squeeze detected: current width near recent minimum
        in_squeeze = current_width <= recent_min_width * 1.1

        if not in_squeeze:
            return 0

        # Direction from momentum
        close = df["close"]
        if len(close) < 5:
            return 0

        momentum = close.iloc[-1] - close.iloc[-5]

        if momentum > 0:
            return 1  # squeeze + upward momentum
        if momentum < 0:
            return -1  # squeeze + downward momentum

        return 0
