"""
Portfolio optimization models.

Implements:
  - KellyCriterion: Optimal betting fraction
  - MeanVarianceOptimizer: Markowitz mean-variance
  - RiskParityOptimizer: Equal risk contribution
  - HierarchicalRiskParity: Lopez de Prado's HRP
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import logging
from typing import Dict, List, Optional

from scipy.optimize import minimize
from scipy.cluster.hierarchy import linkage, fcluster

logger = logging.getLogger(__name__)


# ==================================================================
# Kelly Criterion
# ==================================================================

class KellyCriterion:
    """Optimal position sizing using Kelly Criterion."""

    def __init__(self, max_fraction: float = 0.25, half_kelly: bool = True):
        """
        Args:
            max_fraction: maximum position size cap
            half_kelly: use half-Kelly (more conservative, recommended)
        """
        self.max_fraction = max_fraction
        self.half_kelly = half_kelly

    def calculate(self, win_rate: float, avg_win: float, avg_loss: float) -> float:
        """
        Calculate Kelly fraction.

        Args:
            win_rate: historical win rate (0-1)
            avg_win: average winning trade return
            avg_loss: average losing trade return (positive number)

        Returns:
            Optimal fraction of capital to risk
        """
        if avg_loss <= 0 or win_rate <= 0 or win_rate >= 1:
            return 0.0

        # Kelly formula: f* = (p * b - q) / b
        # where p = win_rate, q = 1 - p, b = avg_win / avg_loss
        b = avg_win / avg_loss
        p = win_rate
        q = 1 - p

        kelly = (p * b - q) / b

        if self.half_kelly:
            kelly *= 0.5

        return max(0.0, min(self.max_fraction, kelly))


# ==================================================================
# Mean-Variance Optimizer (Markowitz)
# ==================================================================

class MeanVarianceOptimizer:
    """Markowitz mean-variance portfolio optimization."""

    def __init__(self, risk_free_rate: float = 0.0, max_weight: float = 0.4):
        self.risk_free_rate = risk_free_rate
        self.max_weight = max_weight

    def optimize(self, returns: pd.DataFrame, target_return: Optional[float] = None) -> Dict[str, float]:
        """
        Optimize portfolio weights for maximum Sharpe ratio.

        Args:
            returns: DataFrame of asset returns (columns = assets)
            target_return: optional target return constraint

        Returns:
            dict of {asset: weight}
        """
        n_assets = returns.shape[1]
        if n_assets == 0:
            return {}

        if n_assets == 1:
            return {returns.columns[0]: 1.0}

        mean_returns = returns.mean().values
        cov_matrix = returns.cov().values

        def neg_sharpe(weights):
            port_return = np.dot(weights, mean_returns)
            port_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
            if port_vol < 1e-10:
                return 0
            return -(port_return - self.risk_free_rate) / port_vol

        # Constraints: weights sum to 1
        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]

        if target_return is not None:
            constraints.append({
                "type": "eq",
                "fun": lambda w: np.dot(w, mean_returns) - target_return
            })

        # Bounds: 0 to max_weight per asset
        bounds = [(0, self.max_weight)] * n_assets

        # Initial guess: equal weight
        w0 = np.ones(n_assets) / n_assets

        result = minimize(neg_sharpe, w0, method="SLSQP",
                          bounds=bounds, constraints=constraints)

        if result.success:
            weights = result.x
        else:
            weights = w0

        return {col: round(float(w), 4) for col, w in zip(returns.columns, weights)}


# ==================================================================
# Risk Parity Optimizer
# ==================================================================

class RiskParityOptimizer:
    """Equal risk contribution portfolio."""

    def optimize(self, returns: pd.DataFrame) -> Dict[str, float]:
        """
        Optimize for equal risk contribution.

        Args:
            returns: DataFrame of asset returns

        Returns:
            dict of {asset: weight}
        """
        n_assets = returns.shape[1]
        if n_assets == 0:
            return {}

        if n_assets == 1:
            return {returns.columns[0]: 1.0}

        cov_matrix = returns.cov().values

        def risk_budget_objective(weights):
            port_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
            if port_vol < 1e-10:
                return 0

            # Marginal risk contribution
            mrc = np.dot(cov_matrix, weights) / port_vol
            rc = weights * mrc

            # Target: equal risk contribution
            target_rc = port_vol / n_assets

            return np.sum((rc - target_rc) ** 2)

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
        bounds = [(0.01, 1.0)] * n_assets
        w0 = np.ones(n_assets) / n_assets

        result = minimize(risk_budget_objective, w0, method="SLSQP",
                          bounds=bounds, constraints=constraints)

        weights = result.x if result.success else w0

        return {col: round(float(w), 4) for col, w in zip(returns.columns, weights)}


# ==================================================================
# Hierarchical Risk Parity (HRP)
# ==================================================================

class HierarchicalRiskParity:
    """
    Lopez de Prado's Hierarchical Risk Parity.
    Uses hierarchical clustering to build diversified portfolios.
    """

    def optimize(self, returns: pd.DataFrame) -> Dict[str, float]:
        """
        HRP portfolio optimization.

        Args:
            returns: DataFrame of asset returns

        Returns:
            dict of {asset: weight}
        """
        n_assets = returns.shape[1]
        if n_assets == 0:
            return {}
        if n_assets == 1:
            return {returns.columns[0]: 1.0}

        cov = returns.cov().values
        corr = returns.corr().values

        # Step 1: Tree clustering
        dist = np.sqrt(0.5 * (1 - corr))
        np.fill_diagonal(dist, 0)

        # Condensed distance matrix
        n = dist.shape[0]
        condensed = []
        for i in range(n):
            for j in range(i + 1, n):
                condensed.append(dist[i, j])
        condensed = np.array(condensed)

        link = linkage(condensed, method="single")

        # Step 2: Quasi-diagonalization
        sort_idx = self._get_quasi_diag(link, n_assets)

        # Step 3: Recursive bisection
        weights = self._recursive_bisection(cov, sort_idx)

        return {returns.columns[i]: round(float(weights[i]), 4) for i in range(n_assets)}

    def _get_quasi_diag(self, link: np.ndarray, n: int) -> list:
        """Get quasi-diagonal order from linkage matrix."""
        sort_idx = pd.Series([link[-1, 0], link[-1, 1]])
        num_items = link[-1, 3]

        while sort_idx.max() >= n:
            sort_idx.index = range(0, sort_idx.shape[0] * 2, 2)
            df0 = sort_idx[sort_idx >= n]
            i = df0.index
            j = df0.values - n

            sort_idx[i] = link[j.astype(int), 0]
            df1 = pd.Series(link[j.astype(int), 1], index=i + 1)
            sort_idx = pd.concat([sort_idx, df1])
            sort_idx = sort_idx.sort_index()
            sort_idx.index = range(sort_idx.shape[0])

        return sort_idx.astype(int).tolist()

    def _recursive_bisection(self, cov: np.ndarray, sort_idx: list) -> np.ndarray:
        """Recursive bisection for weight allocation."""
        n = len(sort_idx)
        weights = np.ones(cov.shape[0])

        items = [sort_idx]

        while len(items) > 0:
            # Bisect each cluster
            next_items = []
            for cluster in items:
                if len(cluster) <= 1:
                    continue

                mid = len(cluster) // 2
                left = cluster[:mid]
                right = cluster[mid:]

                # Inverse-variance allocation
                left_var = self._cluster_var(cov, left)
                right_var = self._cluster_var(cov, right)

                alpha = 1.0 - left_var / (left_var + right_var + 1e-10)

                for idx in left:
                    weights[idx] *= alpha
                for idx in right:
                    weights[idx] *= (1 - alpha)

                if len(left) > 1:
                    next_items.append(left)
                if len(right) > 1:
                    next_items.append(right)

            items = next_items

        # Normalize
        total = weights.sum()
        if total > 0:
            weights /= total

        return weights

    def _cluster_var(self, cov: np.ndarray, cluster: list) -> float:
        """Compute cluster variance (inverse-vol weighted)."""
        sub_cov = cov[np.ix_(cluster, cluster)]
        inv_diag = 1.0 / (np.diag(sub_cov) + 1e-10)
        w = inv_diag / inv_diag.sum()
        return float(np.dot(w.T, np.dot(sub_cov, w)))
