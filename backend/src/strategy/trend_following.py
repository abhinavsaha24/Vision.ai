"""
Trend-following strategies.

Strategies:
  - BreakoutStrategy: N-period high/low breakout
  - MACrossoverStrategy: Moving average crossover
  - DonchianChannelStrategy: Donchian channel breakout
"""

from __future__ import annotations

import pandas as pd


class BreakoutStrategy:
    """Breakout strategy: buy when price breaks above N-period high."""

    def __init__(self, period: int = 20):
        self.period = period

    def generate_signal(self, df: pd.DataFrame) -> int:
        if len(df) < self.period + 1:
            return 0

        close = df["close"].iloc[-1]
        high_n = df["high"].iloc[-(self.period + 1):-1].max()
        low_n = df["low"].iloc[-(self.period + 1):-1].min()

        if close > high_n:
            return 1  # breakout long
        if close < low_n:
            return -1  # breakdown short
        return 0


class MACrossoverStrategy:
    """Moving average crossover strategy."""

    def __init__(self, fast_col: str = "SMA_7", slow_col: str = "SMA_21"):
        self.fast_col = fast_col
        self.slow_col = slow_col

    def generate_signal(self, df: pd.DataFrame) -> int:
        if self.fast_col not in df.columns or self.slow_col not in df.columns:
            return 0

        if len(df) < 3:
            return 0

        fast_now = df[self.fast_col].iloc[-1]
        fast_prev = df[self.fast_col].iloc[-2]
        slow_now = df[self.slow_col].iloc[-1]
        slow_prev = df[self.slow_col].iloc[-2]

        # Crossover: fast crosses above slow
        if fast_prev <= slow_prev and fast_now > slow_now:
            return 1

        # Crossunder: fast crosses below slow
        if fast_prev >= slow_prev and fast_now < slow_now:
            return -1

        return 0


class DonchianChannelStrategy:
    """Donchian channel breakout strategy."""

    def __init__(self, period: int = 20):
        self.period = period

    def generate_signal(self, df: pd.DataFrame) -> int:
        if len(df) < self.period + 1:
            return 0

        close = df["close"].iloc[-1]
        upper = df["high"].iloc[-(self.period + 1):-1].max()
        lower = df["low"].iloc[-(self.period + 1):-1].min()

        if close > upper:
            return 1
        if close < lower:
            return -1
        return 0
