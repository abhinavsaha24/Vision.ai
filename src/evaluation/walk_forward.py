"""
Walk-forward validation for time series models.

Features:
  - Expanding and rolling window modes
  - Per-fold metrics (accuracy, Sharpe, drawdown)
  - Equity curves per fold
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import logging
from dataclasses import dataclass
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardFold:
    """Results for a single walk-forward fold."""
    fold: int
    accuracy: float
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    n_trades: int = 0


class WalkForwardValidator:
    """
    Walk-forward validation with expanding or rolling windows.
    """

    def __init__(self, train_size: float = 0.7, step_size: float = 0.1,
                 mode: str = "rolling"):
        """
        Args:
            train_size: fraction of data for initial training window
            step_size: fraction of data for each test step
            mode: "rolling" (fixed window) or "expanding" (growing window)
        """
        self.train_size = train_size
        self.step_size = step_size
        self.mode = mode

    def run(self, df: pd.DataFrame, feature_cols: list, target_col: str,
            model, price_col: str = "close") -> Dict:
        """
        Run walk-forward validation.

        Args:
            df: DataFrame with features and target
            feature_cols: list of feature column names
            target_col: target column name
            model: sklearn-like model with fit/predict
            price_col: price column for trading metrics

        Returns:
            {mean_accuracy, std_accuracy, folds: [WalkForwardFold], ...}
        """
        n = len(df)
        train_window = int(n * self.train_size)
        step = max(1, int(n * self.step_size))

        folds = []
        fold_num = 0

        start = 0

        while start + train_window + step <= n:
            fold_num += 1

            # Define train/test windows
            if self.mode == "expanding":
                train = df.iloc[0:start + train_window]
            else:
                train = df.iloc[start:start + train_window]

            test = df.iloc[start + train_window:start + train_window + step]

            X_train = train[feature_cols].values
            y_train = train[target_col].values

            X_test = test[feature_cols].values
            y_test = test[target_col].values

            # Replace NaN/Inf
            X_train = np.nan_to_num(X_train, nan=0, posinf=0, neginf=0)
            X_test = np.nan_to_num(X_test, nan=0, posinf=0, neginf=0)

            # Train and predict
            try:
                model.fit(X_train, y_train)
                preds = model.predict(X_test)
                accuracy = float((preds == y_test).mean())
            except Exception as e:
                logger.warning(f"Fold {fold_num} failed: {e}")
                accuracy = 0.0
                preds = np.zeros_like(y_test)

            # Trading metrics for this fold
            sharpe = 0.0
            max_dd = 0.0
            n_trades = 0

            if price_col in test.columns:
                prices = test[price_col].values
                returns = np.diff(prices) / (prices[:-1] + 1e-12)

                # Simple signal → return
                signals = np.where(preds == 1, 1, -1)
                strategy_returns = returns * signals[:-1]

                if len(strategy_returns) > 0 and np.std(strategy_returns) > 0:
                    sharpe = float(np.mean(strategy_returns) / np.std(strategy_returns) * np.sqrt(252))

                equity = (1 + strategy_returns).cumprod()
                if len(equity) > 0:
                    cummax = np.maximum.accumulate(equity)
                    dd = (equity - cummax) / (cummax + 1e-12)
                    max_dd = float(dd.min())

                signal_changes = np.sum(np.abs(np.diff(signals)))
                n_trades = int(signal_changes // 2)

            fold_result = WalkForwardFold(
                fold=fold_num,
                accuracy=accuracy,
                sharpe=sharpe,
                max_drawdown=max_dd,
                n_trades=n_trades,
            )
            folds.append(fold_result)

            start += step

        accuracies = [f.accuracy for f in folds]
        sharpes = [f.sharpe for f in folds]

        return {
            "mean_accuracy": float(np.mean(accuracies)) if accuracies else 0,
            "std_accuracy": float(np.std(accuracies)) if accuracies else 0,
            "mean_sharpe": float(np.mean(sharpes)) if sharpes else 0,
            "n_folds": len(folds),
            "mode": self.mode,
            "folds": [
                {
                    "fold": f.fold,
                    "accuracy": round(f.accuracy, 4),
                    "sharpe": round(f.sharpe, 2),
                    "max_drawdown": round(f.max_drawdown, 4),
                    "n_trades": f.n_trades,
                }
                for f in folds
            ],
        }