"""
Statistical arbitrage strategy: cointegration-based spread trading.

Implements:
  - Engle-Granger cointegration testing
  - Z-score based entry/exit signals
  - Dynamic hedge ratio calculation (rolling OLS)
  - Mean-reverting spread detection

Designed to integrate with StrategyEngine as a plugin strategy.
"""

from __future__ import annotations

import logging
import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class StatisticalArbitrage:
    """
    Statistical arbitrage strategy based on cointegrated pairs.

    Core idea: find two assets whose spread is mean-reverting,
    trade the spread when it deviates from equilibrium.

    Usage:
        arb = StatisticalArbitrage()
        signal = arb.generate_signal(df_a, df_b)
    """

    def __init__(
        self,
        zscore_entry: float = 2.0,
        zscore_exit: float = 0.5,
        lookback: int = 60,
        hedge_window: int = 30,
        min_half_life: int = 5,
        max_half_life: int = 120,
    ):
        self.zscore_entry = zscore_entry
        self.zscore_exit = zscore_exit
        self.lookback = lookback
        self.hedge_window = hedge_window
        self.min_half_life = min_half_life
        self.max_half_life = max_half_life

    # --------------------------------------------------
    # Cointegration testing (Engle-Granger)
    # --------------------------------------------------

    def test_cointegration(self, series_a: pd.Series,
                           series_b: pd.Series) -> Dict:
        """
        Engle-Granger two-step cointegration test.

        Step 1: Regress series_a on series_b
        Step 2: Test residuals for stationarity (ADF)

        Returns:
            dict with cointegrated (bool), p_value, hedge_ratio, half_life
        """
        try:
            from statsmodels.tsa.stattools import adfuller

            # Step 1: OLS regression
            hedge_ratio = self._compute_hedge_ratio(series_a, series_b)
            spread = series_a - hedge_ratio * series_b

            # Step 2: ADF test on spread
            adf_result = adfuller(spread.dropna(), maxlag=10)
            p_value = adf_result[1]

            # Half-life of mean reversion
            half_life = self._compute_half_life(spread)

            cointegrated = (
                p_value < 0.05 and
                self.min_half_life <= half_life <= self.max_half_life
            )

            result = {
                "cointegrated": cointegrated,
                "p_value": round(float(p_value), 6),
                "adf_statistic": round(float(adf_result[0]), 4),
                "hedge_ratio": round(float(hedge_ratio), 6),
                "half_life": round(float(half_life), 1),
                "critical_values": {
                    k: round(float(v), 4)
                    for k, v in adf_result[4].items()
                },
            }

            logger.info(
                f"Cointegration test: p={p_value:.4f}, "
                f"half_life={half_life:.1f}, "
                f"cointegrated={cointegrated}"
            )

            return result

        except ImportError:
            logger.warning("statsmodels not available, using simplified test")
            return self._simplified_cointegration(series_a, series_b)

    def _simplified_cointegration(self, series_a: pd.Series,
                                   series_b: pd.Series) -> Dict:
        """Simplified cointegration check without statsmodels."""
        hedge_ratio = self._compute_hedge_ratio(series_a, series_b)
        spread = series_a - hedge_ratio * series_b

        # Check if spread variance is bounded
        spread_std = spread.std()
        spread_range = spread.max() - spread.min()
        is_bounded = spread_range < 4 * spread_std

        half_life = self._compute_half_life(spread)

        return {
            "cointegrated": is_bounded and self.min_half_life <= half_life <= self.max_half_life,
            "p_value": 0.01 if is_bounded else 0.5,
            "hedge_ratio": round(float(hedge_ratio), 6),
            "half_life": round(float(half_life), 1),
            "method": "simplified",
        }

    # --------------------------------------------------
    # Hedge ratio
    # --------------------------------------------------

    def _compute_hedge_ratio(self, series_a: pd.Series,
                              series_b: pd.Series) -> float:
        """Compute OLS hedge ratio (beta) between two series."""
        b = series_b.values
        a = series_a.values

        # OLS: a = beta * b + alpha + epsilon
        # beta = cov(a, b) / var(b)
        cov = np.cov(a, b)
        if cov[1, 1] == 0:
            return 1.0
        return float(cov[0, 1] / cov[1, 1])

    def compute_rolling_hedge_ratio(self, series_a: pd.Series,
                                     series_b: pd.Series,
                                     window: int = None) -> pd.Series:
        """Compute rolling hedge ratio for dynamic adjustment."""
        window = window or self.hedge_window

        ratios = []
        for i in range(window, len(series_a)):
            a_win = series_a.iloc[i - window:i]
            b_win = series_b.iloc[i - window:i]
            ratio = self._compute_hedge_ratio(a_win, b_win)
            ratios.append(ratio)

        return pd.Series(ratios, index=series_a.index[window:])

    # --------------------------------------------------
    # Half-life of mean reversion
    # --------------------------------------------------

    def _compute_half_life(self, spread: pd.Series) -> float:
        """
        Compute Ornstein-Uhlenbeck half-life of mean reversion.

        dS = theta * (mu - S) * dt + sigma * dW
        half_life = -ln(2) / theta

        Estimated via OLS: delta_spread = theta * spread_lag + intercept
        """
        spread_clean = spread.dropna()
        if len(spread_clean) < 10:
            return float('inf')

        spread_lag = spread_clean.shift(1).dropna()
        delta = spread_clean.diff().dropna()

        # Align
        min_len = min(len(spread_lag), len(delta))
        spread_lag = spread_lag.iloc[-min_len:]
        delta = delta.iloc[-min_len:]

        # OLS: delta = theta * spread_lag + const
        x = spread_lag.values
        y = delta.values

        if np.var(x) == 0:
            return float('inf')

        theta = np.cov(x, y)[0, 1] / np.var(x)

        if theta >= 0:
            return float('inf')  # Not mean-reverting

        return -np.log(2) / theta

    # --------------------------------------------------
    # Signal generation
    # --------------------------------------------------

    def compute_spread(self, series_a: pd.Series,
                       series_b: pd.Series,
                       hedge_ratio: float = None) -> pd.Series:
        """Compute the spread between two series."""
        if hedge_ratio is None:
            hedge_ratio = self._compute_hedge_ratio(series_a, series_b)
        return series_a - hedge_ratio * series_b

    def compute_zscore(self, spread: pd.Series,
                       window: int = None) -> pd.Series:
        """Compute rolling z-score of the spread."""
        window = window or self.lookback
        mean = spread.rolling(window).mean()
        std = spread.rolling(window).std()
        std = std.replace(0, np.nan)
        return (spread - mean) / std

    def generate_signal(self, series_a: pd.Series,
                        series_b: pd.Series) -> Dict:
        """
        Generate stat arb trading signal.

        Returns:
            dict with direction, z_score, hedge_ratio, confidence
        """
        # Compute spread and z-score
        hedge_ratio = self._compute_hedge_ratio(series_a, series_b)
        spread = self.compute_spread(series_a, series_b, hedge_ratio)
        zscore = self.compute_zscore(spread)

        current_z = float(zscore.iloc[-1]) if not zscore.empty and not np.isnan(zscore.iloc[-1]) else 0.0

        # Signal logic
        direction = "FLAT"
        confidence = 0.0

        if current_z > self.zscore_entry:
            # Spread is too high → short spread (sell A, buy B)
            direction = "SHORT_SPREAD"
            confidence = min(abs(current_z) / (self.zscore_entry * 2), 1.0)

        elif current_z < -self.zscore_entry:
            # Spread is too low → long spread (buy A, sell B)
            direction = "LONG_SPREAD"
            confidence = min(abs(current_z) / (self.zscore_entry * 2), 1.0)

        elif abs(current_z) < self.zscore_exit:
            # Near equilibrium → exit any position
            direction = "EXIT"
            confidence = 1.0 - abs(current_z)

        return {
            "direction": direction,
            "z_score": round(current_z, 4),
            "hedge_ratio": round(hedge_ratio, 6),
            "spread_current": round(float(spread.iloc[-1]), 4) if not spread.empty else 0,
            "confidence": round(confidence, 4),
            "entry_threshold": self.zscore_entry,
            "exit_threshold": self.zscore_exit,
        }

    # --------------------------------------------------
    # Utility: find cointegrated pairs
    # --------------------------------------------------

    def find_pairs(self, price_dict: Dict[str, pd.Series],
                   max_pairs: int = 5) -> list:
        """
        Scan a universe of assets for cointegrated pairs.

        Args:
            price_dict: {symbol: price_series}
            max_pairs: max number of pairs to return

        Returns:
            list of dicts with pair info sorted by p-value
        """
        symbols = list(price_dict.keys())
        pairs = []

        for i in range(len(symbols)):
            for j in range(i + 1, len(symbols)):
                result = self.test_cointegration(
                    price_dict[symbols[i]],
                    price_dict[symbols[j]],
                )
                if result["cointegrated"]:
                    pairs.append({
                        "pair": (symbols[i], symbols[j]),
                        "p_value": result["p_value"],
                        "hedge_ratio": result["hedge_ratio"],
                        "half_life": result["half_life"],
                    })

        # Sort by p-value (most significant first)
        pairs.sort(key=lambda x: x["p_value"])
        return pairs[:max_pairs]
