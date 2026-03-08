"""
Evaluation metrics: classification (accuracy, precision, recall, F1, confusion matrix)
and trading (Sharpe, win rate, profit factor, max drawdown).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np


@dataclass
class ClassificationMetrics:
    """Classification metrics and confusion matrix."""

    accuracy: float
    precision: float
    recall: float
    f1: float
    confusion_matrix: List[List[int]]


def compute_classification_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
) -> ClassificationMetrics:
    """
    Compute accuracy, precision, recall, F1, and 2x2 confusion matrix.
    Assumes binary labels in {0, 1}.
    """
    y_true = np.asarray(y_true).ravel()
    y_pred = np.asarray(y_pred).ravel()
    tp = int(np.sum((y_pred == 1) & (y_true == 1)))
    tn = int(np.sum((y_pred == 0) & (y_true == 0)))
    fp = int(np.sum((y_pred == 1) & (y_true == 0)))
    fn = int(np.sum((y_pred == 0) & (y_true == 1)))
    cm = [[tn, fp], [fn, tp]]
    n = len(y_true)
    accuracy = (tp + tn) / n if n else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return ClassificationMetrics(
        accuracy=float(accuracy),
        precision=float(precision),
        recall=float(recall),
        f1=float(f1),
        confusion_matrix=cm,
    )


@dataclass
class TradingMetrics:
    """Trading performance metrics."""

    sharpe_ratio: float
    win_rate: float
    profit_factor: float
    max_drawdown: float
    total_return: float
    num_trades: int


def compute_trading_metrics(
    equity_curve: np.ndarray,
    trades_pnl: np.ndarray,
    periods_per_year: float = 252.0,
) -> TradingMetrics:
    """
    Compute Sharpe, win rate, profit factor, max drawdown from equity curve and trade PnLs.
    equity_curve: array of portfolio value over time (length T+1).
    trades_pnl: array of PnL per closed trade.
    """
    equity_curve = np.asarray(equity_curve).ravel()
    trades_pnl = np.asarray(trades_pnl).ravel()
    if len(equity_curve) < 2:
        ret = 0.0
        sharpe = 0.0
        max_dd = 0.0
    else:
        ret = (equity_curve[-1] - equity_curve[0]) / equity_curve[0]
        returns = np.diff(equity_curve) / (equity_curve[:-1] + 1e-12)
        returns = returns[~np.isnan(returns)]
        if len(returns) > 0 and np.std(returns) > 0:
            sharpe = float(np.mean(returns) / np.std(returns) * np.sqrt(periods_per_year))
        else:
            sharpe = 0.0
        cummax = np.maximum.accumulate(equity_curve)
        drawdowns = (equity_curve - cummax) / (cummax + 1e-12)
        max_dd = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0

    n_trades = len(trades_pnl)
    if n_trades == 0:
        win_rate = 0.0
        profit_factor = 0.0
    else:
        wins = trades_pnl[trades_pnl > 0]
        losses = trades_pnl[trades_pnl < 0]
        win_rate = float(len(wins) / n_trades)
        gross_profit = float(np.sum(wins)) if len(wins) > 0 else 0.0
        gross_loss = float(np.abs(np.sum(losses))) if len(losses) > 0 else 1e-12
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

    return TradingMetrics(
        sharpe_ratio=sharpe,
        win_rate=win_rate,
        profit_factor=profit_factor,
        max_drawdown=max_dd,
        total_return=ret,
        num_trades=n_trades,
    )
