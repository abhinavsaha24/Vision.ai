"""
Pairs / statistical arbitrage trading strategy.

Strategy:
  - CointegrationStrategy: Trade spread of cointegrated pairs
"""

from __future__ import annotations

import logging
import numpy as np
import pandas as pd
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class CointegrationStrategy:
    """
    Pairs trading using z-score of the spread between two price series.

    The strategy:
    1. Compute spread = price_a - hedge_ratio * price_b
    2. Compute z-score of spread
    3. Enter when z-score exceeds threshold, exit at mean
    """

    def __init__(self, entry_z: float = 2.0, exit_z: float = 0.5,
                 lookback: int = 60):
        self.entry_z = entry_z
        self.exit_z = exit_z
        self.lookback = lookback
        self.hedge_ratio: Optional[float] = None

    def fit(self, price_a: pd.Series, price_b: pd.Series) -> "CointegrationStrategy":
        """Estimate hedge ratio via OLS regression."""
        if len(price_a) < self.lookback:
            self.hedge_ratio = 1.0
            return self

        y = price_a.values[-self.lookback:]
        x = price_b.values[-self.lookback:]

        # OLS: y = beta * x + alpha
        x_mean = x.mean()
        y_mean = y.mean()
        beta = np.sum((x - x_mean) * (y - y_mean)) / (np.sum((x - x_mean) ** 2) + 1e-10)

        self.hedge_ratio = float(beta)
        return self

    def compute_spread(self, price_a: pd.Series, price_b: pd.Series) -> pd.Series:
        """Compute spread between pair."""
        if self.hedge_ratio is None:
            self.fit(price_a, price_b)

        return price_a - self.hedge_ratio * price_b

    def generate_signal(self, price_a: pd.Series, price_b: pd.Series) -> int:
        """Generate trading signal for the pair."""
        if len(price_a) < self.lookback:
            return 0

        self.fit(price_a, price_b)
        spread = self.compute_spread(price_a, price_b)

        # Z-score of spread
        spread_recent = spread.iloc[-self.lookback:]
        z = (spread.iloc[-1] - spread_recent.mean()) / (spread_recent.std() + 1e-10)

        if z > self.entry_z:
            return -1  # spread too high → short spread (short A, long B)
        if z < -self.entry_z:
            return 1  # spread too low → long spread (long A, short B)
        if abs(z) < self.exit_z:
            return 0  # close position (mean reversion complete)

        return 0

    def get_spread_stats(self, price_a: pd.Series, price_b: pd.Series) -> dict:
        """Return spread statistics for analysis."""
        spread = self.compute_spread(price_a, price_b)
        spread_recent = spread.iloc[-self.lookback:]

        z = (spread.iloc[-1] - spread_recent.mean()) / (spread_recent.std() + 1e-10)

        return {
            "hedge_ratio": self.hedge_ratio,
            "z_score": float(z),
            "spread_mean": float(spread_recent.mean()),
            "spread_std": float(spread_recent.std()),
            "current_spread": float(spread.iloc[-1]),
        }
