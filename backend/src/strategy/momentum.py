"""
Momentum trading strategies — research-backed implementation.

Based on: Time-series and cross-sectional momentum (Moskowitz et al.)

Time-series momentum:
  s_t = MA_fast - MA_slow  (or cumulative return over lookback)
  Long if s_t > 0, Short if s_t < 0

Cross-sectional momentum:
  Rank assets by past returns, long top quantile, short bottom quantile.

Features:
  - Configurable lookback windows
  - Volatility-adjusted signal strength
  - Dual-mode: time-series (single asset) and cross-sectional (multi-asset)
"""

from __future__ import annotations

import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class MomentumStrategy:
    """
    Time-series momentum strategy for a single asset.

    Signal logic:
      1. Compute cumulative return over lookback period
      2. Compute MA crossover (fast vs slow)
      3. Combine both signals with volatility normalization
      4. Return +1 (long), -1 (short), or 0 (flat)

    Parameters:
        lookback: return lookback period (bars)
        fast_period: fast moving average period
        slow_period: slow moving average period
        vol_lookback: volatility normalization window
    """

    def __init__(self, lookback: int = 20, fast_period: int = 7,
                 slow_period: int = 21, vol_lookback: int = 20):
        self.lookback = lookback
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.vol_lookback = vol_lookback

    def generate_signal(self, df: pd.DataFrame = None, **kwargs) -> int:
        """Generate momentum signal from price data."""
        if df is None or "close" not in df.columns:
            return 0
        if len(df) < max(self.slow_period, self.lookback) + 1:
            return 0

        try:
            close = df["close"]

            # --- Signal 1: Cumulative return momentum ---
            # s_t = price_now / price_lookback_ago - 1
            ret_momentum = close.iloc[-1] / close.iloc[-self.lookback] - 1

            # --- Signal 2: MA crossover ---
            # s_t = MA_fast - MA_slow
            ma_fast = close.iloc[-self.fast_period:].mean()
            ma_slow = close.iloc[-self.slow_period:].mean()
            ma_signal = (ma_fast - ma_slow) / (ma_slow + 1e-10)

            # --- Volatility normalization ---
            returns = close.pct_change().dropna()
            if len(returns) >= self.vol_lookback:
                vol = returns.iloc[-self.vol_lookback:].std()
                if vol > 0:
                    # Normalize by volatility to get comparable signal strength
                    ret_momentum = ret_momentum / (vol * np.sqrt(self.lookback))
                    ma_signal = ma_signal / vol

            # --- Combine signals (equal weight) ---
            composite = 0.5 * np.sign(ret_momentum) + 0.5 * np.sign(ma_signal)

            # Only trade when both agree or one is strong
            if composite > 0.3:
                return 1
            elif composite < -0.3:
                return -1
            return 0

        except Exception as e:
            logger.error(f"MomentumStrategy error: {e}")
            return 0


class CrossSectionalMomentum:
    """
    Cross-sectional momentum for multi-asset ranking.

    Ranks assets by past returns, longs top quantile, shorts bottom.
    Used for portfolio-level allocation decisions.

    Parameters:
        lookback: return lookback period
        top_quantile: fraction of winners to long
        bottom_quantile: fraction of losers to short
    """

    def __init__(self, lookback: int = 60, top_quantile: float = 0.2,
                 bottom_quantile: float = 0.2):
        self.lookback = lookback
        self.top_quantile = top_quantile
        self.bottom_quantile = bottom_quantile

    def rank_assets(self, price_dict: dict) -> dict:
        """
        Rank assets by past return and return target weights.

        Args:
            price_dict: {symbol: pd.Series of close prices}

        Returns:
            {symbol: weight} (positive for longs, negative for shorts)
        """
        if not price_dict:
            return {}

        try:
            past_returns = {}
            for symbol, prices in price_dict.items():
                if len(prices) < self.lookback + 1:
                    continue
                ret = prices.iloc[-1] / prices.iloc[-self.lookback] - 1
                if np.isfinite(ret):
                    past_returns[symbol] = ret

            if len(past_returns) < 3:
                return {}

            # Sort by return (ascending)
            ranked = sorted(past_returns.items(), key=lambda x: x[1])
            n = len(ranked)

            n_short = max(1, int(self.bottom_quantile * n))
            n_long = max(1, int(self.top_quantile * n))

            weights = {}
            # Short losers
            for symbol, _ in ranked[:n_short]:
                weights[symbol] = -1.0 / n_short

            # Long winners
            for symbol, _ in ranked[-n_long:]:
                weights[symbol] = 1.0 / n_long

            return weights

        except Exception as e:
            logger.error(f"CrossSectionalMomentum error: {e}")
            return {}