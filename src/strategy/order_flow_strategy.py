"""
Order flow / volume-based strategies.

Strategies:
  - VolumeSpikeStrategy: Detect abnormal volume
  - OrderBookImbalanceStrategy: Buy/sell pressure from close position
"""

from __future__ import annotations

import pandas as pd
import numpy as np


class VolumeSpikeStrategy:
    """Trade on abnormal volume spikes."""

    def __init__(self, volume_threshold: float = 2.0):
        self.volume_threshold = volume_threshold

    def generate_signal(self, df: pd.DataFrame) -> int:
        if "volume_ratio" not in df.columns:
            return 0

        vol_ratio = df["volume_ratio"].iloc[-1]

        if vol_ratio < self.volume_threshold:
            return 0  # no spike

        # Direction from price movement
        if len(df) < 2:
            return 0

        price_change = df["close"].iloc[-1] - df["close"].iloc[-2]

        if price_change > 0:
            return 1  # volume spike + price up → bullish
        if price_change < 0:
            return -1  # volume spike + price down → bearish

        return 0


class OrderBookImbalanceStrategy:
    """
    Proxy order book imbalance from close position within bar.
    Close near high → buy pressure, close near low → sell pressure.
    """

    def __init__(self, imbalance_threshold: float = 0.7):
        self.imbalance_threshold = imbalance_threshold

    def generate_signal(self, df: pd.DataFrame) -> int:
        if "close_position" not in df.columns or len(df) < 3:
            return 0

        # Average close position over last 3 bars
        recent = df["close_position"].iloc[-3:].mean()

        if recent > self.imbalance_threshold:
            return 1  # buy pressure (close near high)
        if recent < (1 - self.imbalance_threshold):
            return -1  # sell pressure (close near low)

        return 0
