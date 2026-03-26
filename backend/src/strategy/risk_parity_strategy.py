"""
Risk parity allocation strategy — research-backed implementation.

Based on: Equal Risk Contribution (Maillard, Roncalli, Teiletche 2010)

Mathematical framework:
  Portfolio variance: σ²_p = w^T Σ w
  Marginal contribution of asset i: (Σw)_i
  Risk contribution: RC_i = w_i · (Σw)_i
  Risk parity: RC_i = (1/N) · σ²_p for all i

Naive risk parity (diagonal Σ):
  w_i ∝ 1/σ_i

Features:
  - Inverse-volatility weighting (naive risk parity)
  - Full ERC optimization (when scipy available)
  - Vol-targeting signal for single-asset usage
  - Position scalar for dynamic sizing
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class RiskParityStrategy:
    """
    Risk parity / vol-targeting strategy.

    Single-asset mode: acts as a vol-targeting position filter.
    Multi-asset mode: computes inverse-vol or ERC weights.

    Parameters:
        vol_target: target annualized volatility (default 15%)
        vol_lookback: lookback for realized volatility
        rebalance_frequency: days between rebalances
    """

    def __init__(
        self,
        vol_target: float = 0.15,
        vol_lookback: int = 20,
        rebalance_frequency: int = 20,
    ):
        self.vol_target = vol_target
        self.vol_lookback = vol_lookback
        self.rebalance_frequency = rebalance_frequency

    def generate_signal(self, df: pd.DataFrame = None, **kwargs) -> int:
        """
        Single-asset vol-targeting signal.

        Long when realized vol < target (safe environment).
        Flat/Short when realized vol >> target (risky environment).
        """
        if df is None or len(df) < self.vol_lookback + 5:
            return 0

        try:
            if "close" not in df.columns:
                return 0

            returns = df["close"].pct_change().dropna()
            if len(returns) < self.vol_lookback:
                return 0

            # Annualized realized volatility
            realized_vol = float(
                returns.iloc[-self.vol_lookback :].std() * np.sqrt(252)
            )

            if realized_vol <= 0:
                return 0

            vol_ratio = self.vol_target / realized_vol

            if vol_ratio > 1.0:
                return 1  # vol below target → safe to be long
            elif vol_ratio < 0.5:
                return -1  # vol 2x target → dangerous → reduce
            else:
                return 0  # vol near target → neutral

        except Exception as e:
            logger.error("RiskParityStrategy signal error: %s", e)
            return 0

    def get_position_scalar(self, df: pd.DataFrame) -> float:
        """
        Compute vol-targeting position scalar.

        scalar = target_vol / realized_vol
        Clamped to [0.1, 2.0] for safety.
        """
        if df is None or len(df) < self.vol_lookback:
            return 1.0

        try:
            returns = df["close"].pct_change().dropna()
            realized_vol = float(
                returns.iloc[-self.vol_lookback :].std() * np.sqrt(252)
            )

            if realized_vol <= 0:
                return 1.0

            scalar = self.vol_target / realized_vol
            return float(np.clip(scalar, 0.1, 2.0))

        except Exception:
            return 1.0

    # --------------------------------------------------
    # Multi-Asset Risk Parity
    # --------------------------------------------------

    def inverse_volatility_weights(
        self, returns_dict: Dict[str, pd.Series], lookback: int = None
    ) -> Dict[str, float]:
        """
        Naive risk parity: inverse-volatility weights.

        w_i ∝ 1/σ_i

        Args:
            returns_dict: {symbol: returns_series}
            lookback: rolling window

        Returns:
            {symbol: weight}
        """
        lookback = lookback or self.vol_lookback
        inv_vols = {}

        for symbol, returns in returns_dict.items():
            if len(returns) < lookback:
                continue
            vol = returns.iloc[-lookback:].std()
            if vol > 0:
                inv_vols[symbol] = 1.0 / vol

        if not inv_vols:
            return {}

        total = sum(inv_vols.values())
        return {s: v / total for s, v in inv_vols.items()}

    def equal_risk_contribution(
        self, returns_df: pd.DataFrame, risk_budget: Optional[np.ndarray] = None
    ) -> Dict[str, float]:
        """
        Full Equal Risk Contribution optimization.

        Minimizes: Σ_i (RC_i - b_i)² where b_i are risk budgets
        Subject to: Σ w_i = 1, w_i >= 0

        Falls back to inverse-vol if scipy is unavailable.
        """
        try:
            from scipy.optimize import minimize

            n = returns_df.shape[1]
            cov = returns_df.cov().values

            if risk_budget is None:
                risk_budget = np.ones(n) / n  # equal budget

            def objective(w):
                """Minimize sum of (RC_i - budget_i * total_risk)²"""
                w = np.array(w)
                sigma_p_sq = w @ cov @ w
                marginal_contrib = cov @ w
                risk_contrib = w * marginal_contrib

                # Normalize to get RC as fraction of total risk
                if sigma_p_sq > 0:
                    rc_pct = risk_contrib / sigma_p_sq
                else:
                    rc_pct = np.ones(n) / n

                return float(np.sum((rc_pct - risk_budget) ** 2))

            # Initial guess: inverse-vol
            vols = np.sqrt(np.diag(cov))
            vols = np.where(vols > 0, vols, 1e-6)
            w0 = (1.0 / vols) / np.sum(1.0 / vols)

            # Constraints and bounds
            constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}
            bounds = [(0.01, 0.5) for _ in range(n)]

            result = minimize(
                objective,
                w0,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"maxiter": 200, "ftol": 1e-10},
            )

            if result.success:
                weights = result.x
                return {
                    col: round(float(w), 6)
                    for col, w in zip(returns_df.columns, weights)
                }

            # Fallback to inverse-vol
            logger.warning("ERC optimization failed, using inverse-vol")

        except ImportError:
            logger.info("scipy not available, using inverse-vol weights")
        except Exception as e:
            logger.warning("ERC optimization error: %s", e)

        # Fallback: inverse-vol
        returns_dict = {col: returns_df[col] for col in returns_df.columns}
        return self.inverse_volatility_weights(returns_dict)
