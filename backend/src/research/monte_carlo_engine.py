"""Institutional Monte Carlo stress testing engine."""

from __future__ import annotations

from typing import Dict

import numpy as np


class MonteCarloEngine:
    """Simulates thousands of stressed paths with volatility and liquidity shocks."""

    def __init__(self, initial_capital: float = 100000.0):
        self.initial_capital = initial_capital

    def simulate(
        self,
        returns: np.ndarray,
        n_paths: int = 10000,
        shock_prob: float = 0.01,
        shock_scale: float = 4.0,
        liquidity_drought_prob: float = 0.02,
    ) -> Dict:
        if returns is None or len(returns) < 30:
            return {"error": "insufficient_returns"}

        returns = np.asarray(returns, dtype=float)
        paths_final = []
        paths_sharpe = []
        paths_mdd = []

        for _ in range(n_paths):
            sample = np.random.choice(returns, size=len(returns), replace=True)

            # Flash crash / volatility spike shocks
            shock_mask = np.random.rand(len(sample)) < shock_prob
            shock_values = np.random.normal(
                -abs(sample.std()) * shock_scale, abs(sample.std()), size=len(sample)
            )
            sample[shock_mask] += shock_values[shock_mask]

            # Liquidity drought magnifies adverse returns
            drought_mask = np.random.rand(len(sample)) < liquidity_drought_prob
            sample[drought_mask & (sample < 0)] *= 1.5

            equity = self.initial_capital * np.cumprod(1 + sample)
            total_return = (equity[-1] - self.initial_capital) / self.initial_capital

            peak = np.maximum.accumulate(equity)
            drawdown = (equity - peak) / peak
            mdd = float(drawdown.min())

            sharpe = (
                float((np.mean(sample) / np.std(sample)) * np.sqrt(252))
                if np.std(sample) > 0
                else 0.0
            )

            paths_final.append(total_return)
            paths_sharpe.append(sharpe)
            paths_mdd.append(mdd)

        final = np.array(paths_final)
        sharpe_arr = np.array(paths_sharpe)
        mdd_arr = np.array(paths_mdd)

        return {
            "n_paths": n_paths,
            "median_return": float(np.median(final)),
            "p05_return": float(np.percentile(final, 5)),
            "p95_return": float(np.percentile(final, 95)),
            "probability_of_ruin": float(np.mean(final <= -0.5)),
            "expected_drawdown": float(np.mean(mdd_arr)),
            "tail_drawdown_p95": float(np.percentile(mdd_arr, 95)),
            "sharpe_median": float(np.median(sharpe_arr)),
            "sharpe_p05": float(np.percentile(sharpe_arr, 5)),
            "sharpe_p95": float(np.percentile(sharpe_arr, 95)),
        }
