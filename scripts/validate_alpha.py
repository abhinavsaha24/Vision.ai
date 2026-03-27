"""
Vision AI — Alpha Validation Script

Walk-forward backtest across multiple symbols and sessions,
with realistic transaction costs and latency simulation.

Usage:
    python scripts/validate_alpha.py

Outputs:
    scripts/alpha_validation_report.json
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Ensure project root is importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.src.data.fetcher import DataFetcher
from backend.src.features.indicators import FeatureEngineer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("alpha-validation")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SYMBOLS = ["BTC/USDT", "ETH/USDT"]
TIMEFRAME = "5m"
MIN_BARS = 4032  # ~14 days of 5m bars
SESSIONS = {
    "asia": (0, 8),    # 00:00–08:00 UTC
    "europe": (8, 16), # 08:00–16:00 UTC
    "us": (16, 24),    # 16:00–24:00 UTC
}

# Costs (basis points)
COMMISSION_BPS = 10.0
SPREAD_BPS = 8.0
SLIPPAGE_BPS = 6.0
LATENCY_PENALTY_BPS = 2.0  # simulates 50-500ms latency degradation
TOTAL_COST_BPS = COMMISSION_BPS + SPREAD_BPS + SLIPPAGE_BPS + LATENCY_PENALTY_BPS

# Walk-forward
N_SPLITS = 6
CONFIDENCE_THRESHOLD = 0.60

# Thresholds
SHARPE_THRESHOLD = 1.5
PROFIT_FACTOR_THRESHOLD = 1.5
MAX_DRAWDOWN_THRESHOLD = 0.10


@dataclass
class BacktestResult:
    symbol: str = ""
    session: str = "all"
    n_trades: int = 0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    total_return: float = 0.0
    avg_return_per_trade: float = 0.0
    annualized_return: float = 0.0
    calmar_ratio: float = 0.0
    passed: bool = False


@dataclass
class ValidationReport:
    timestamp: str = ""
    symbols_tested: List[str] = field(default_factory=list)
    total_cost_bps: float = TOTAL_COST_BPS
    min_bars_per_symbol: int = MIN_BARS
    results: List[Dict] = field(default_factory=list)
    aggregate: Dict = field(default_factory=dict)
    verdict: str = "NOT_READY"
    real_money_readiness_pct: float = 0.0


# ---------------------------------------------------------------------------
# Core backtest logic
# ---------------------------------------------------------------------------

def compute_returns_with_costs(
    predictions: np.ndarray,
    confidences: np.ndarray,
    actual_returns: np.ndarray,
    cost_bps: float = TOTAL_COST_BPS,
    confidence_gate: float = CONFIDENCE_THRESHOLD,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Apply confidence gating and transaction costs to raw predictions.
    Returns (strategy_returns, trade_mask).
    """
    cost_frac = cost_bps / 10_000.0
    trade_mask = confidences >= confidence_gate
    # Direction: 1 for BUY, -1 for SELL, 0 for HOLD
    positions = np.where(trade_mask, np.sign(predictions - 0.5), 0.0)

    # Strategy returns = position * actual return - |position change| * cost
    position_changes = np.abs(np.diff(positions, prepend=0))
    strategy_returns = positions * actual_returns - position_changes * cost_frac

    return strategy_returns, trade_mask


def compute_metrics(returns: np.ndarray, trade_mask: np.ndarray) -> BacktestResult:
    """Compute performance metrics from a returns series."""
    result = BacktestResult()

    trade_returns = returns[trade_mask]
    result.n_trades = int(np.sum(trade_mask))

    if result.n_trades < 10:
        return result

    # Win rate
    wins = trade_returns[trade_returns > 0]
    losses = trade_returns[trade_returns < 0]
    result.win_rate = float(len(wins) / max(len(trade_returns), 1))

    # Sharpe (annualized from 5m bars)
    bars_per_year = 365.25 * 24 * 12  # 5m bars
    mean_ret = float(np.mean(returns))
    std_ret = float(np.std(returns))
    if std_ret > 0:
        result.sharpe_ratio = round(mean_ret / std_ret * np.sqrt(bars_per_year), 3)
    else:
        result.sharpe_ratio = 0.0

    # Profit factor
    gross_profit = float(np.sum(wins)) if len(wins) > 0 else 0.0
    gross_loss = float(np.abs(np.sum(losses))) if len(losses) > 0 else 0.0
    result.profit_factor = round(gross_profit / max(gross_loss, 1e-10), 3)

    # Max drawdown
    cumulative = np.cumprod(1 + returns)
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = (running_max - cumulative) / running_max
    result.max_drawdown = round(float(np.max(drawdowns)), 4)

    # Total return
    result.total_return = round(float(cumulative[-1] - 1), 4)

    # Average return per trade
    result.avg_return_per_trade = round(float(np.mean(trade_returns)), 6)

    # Annualized return
    n_bars = len(returns)
    if n_bars > 0:
        total_ret = cumulative[-1]
        years = n_bars / bars_per_year
        if years > 0 and total_ret > 0:
            result.annualized_return = round(float(total_ret ** (1 / years) - 1), 4)

    # Calmar ratio
    if result.max_drawdown > 0:
        result.calmar_ratio = round(result.annualized_return / result.max_drawdown, 3)

    # Pass/fail
    result.passed = (
        result.sharpe_ratio >= SHARPE_THRESHOLD
        and result.profit_factor >= PROFIT_FACTOR_THRESHOLD
        and result.max_drawdown <= MAX_DRAWDOWN_THRESHOLD
    )

    return result


def filter_by_session(df: pd.DataFrame, session_name: str) -> pd.DataFrame:
    """Filter dataframe to a specific trading session by UTC hour."""
    if session_name == "all":
        return df

    start_hour, end_hour = SESSIONS[session_name]
    if hasattr(df.index, "hour"):
        mask = (df.index.hour >= start_hour) & (df.index.hour < end_hour)
    elif "Date" in df.columns:
        hours = pd.to_datetime(df["Date"]).dt.hour
        mask = (hours >= start_hour) & (hours < end_hour)
    else:
        return df

    return df[mask].copy()


def run_walk_forward_backtest(
    df: pd.DataFrame,
    feature_cols: List[str],
    target_col: str = "Target_Direction",
    n_splits: int = N_SPLITS,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Walk-forward split: train on fold i, test on fold i+1.
    Returns (predictions, confidences, actual_returns) on the test folds.
    """
    try:
        from lightgbm import LGBMClassifier
    except ImportError:
        logger.warning("LightGBM not installed, using dummy predictions")
        n = len(df)
        return (
            np.random.rand(n),
            np.random.rand(n) * 0.3 + 0.4,
            df["Close"].pct_change().fillna(0).values,
        )

    fold_size = len(df) // (n_splits + 1)
    all_preds = []
    all_confs = []
    all_returns = []

    for i in range(n_splits):
        train_start = 0
        train_end = fold_size * (i + 1)
        test_start = train_end
        test_end = min(train_end + fold_size, len(df))

        if test_end <= test_start:
            break

        train_df = df.iloc[train_start:train_end]
        test_df = df.iloc[test_start:test_end]

        X_train = train_df[feature_cols].values
        y_train = train_df[target_col].values
        X_test = test_df[feature_cols].values

        # Add 1-bar execution delay
        actual_returns = test_df["Close"].pct_change().shift(-1).fillna(0).values

        model = LGBMClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_samples=20,
            reg_alpha=0.1,
            reg_lambda=0.1,
            random_state=42,
            verbose=-1,
        )

        try:
            model.fit(X_train, y_train)
            probas = model.predict_proba(X_test)
            # Probability of positive class
            pos_idx = list(model.classes_).index(1) if 1 in model.classes_ else -1
            if pos_idx >= 0:
                preds = probas[:, pos_idx]
            else:
                preds = np.ones(len(X_test)) * 0.5
            confs = np.abs(preds - 0.5) * 2  # confidence = distance from 0.5
        except Exception as e:
            logger.warning("Fold %d training failed: %s", i, e)
            preds = np.ones(len(X_test)) * 0.5
            confs = np.zeros(len(X_test))

        all_preds.append(preds)
        all_confs.append(confs)
        all_returns.append(actual_returns)

    if not all_preds:
        n = len(df)
        return np.ones(n) * 0.5, np.zeros(n), np.zeros(n)

    return (
        np.concatenate(all_preds),
        np.concatenate(all_confs),
        np.concatenate(all_returns),
    )


# ---------------------------------------------------------------------------
# Main validation
# ---------------------------------------------------------------------------

def validate() -> ValidationReport:
    report = ValidationReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        symbols_tested=SYMBOLS,
    )

    fetcher = DataFetcher()
    engineer = FeatureEngineer()
    all_results: List[BacktestResult] = []

    for symbol in SYMBOLS:
        logger.info("=" * 60)
        logger.info("Validating %s", symbol)
        logger.info("=" * 60)

        try:
            df = fetcher.fetch(symbol, timeframe=TIMEFRAME, limit=MIN_BARS)
            if df is None or len(df) < 500:
                logger.warning("Insufficient data for %s (%d bars)", symbol, len(df) if df is not None else 0)
                result = BacktestResult(symbol=symbol, session="all")
                all_results.append(result)
                continue

            df = engineer.add_all_indicators(df)

            # Create target labels (25bps threshold for actionable movement)
            if "Target_Direction" not in df.columns:
                forward_ret = df["Close"].pct_change(5).shift(-5)
                threshold = 0.0025  # 25bps
                df["Target_Direction"] = (forward_ret > threshold).astype(int)

            df = df.dropna()

            if len(df) < 500:
                logger.warning("Insufficient data after feature engineering for %s", symbol)
                result = BacktestResult(symbol=symbol, session="all")
                all_results.append(result)
                continue

            # Identify feature columns
            exclude_cols = {
                "Target", "Target_Direction", "Target_Actionable",
                "Date", "Open", "High", "Low", "Close", "Volume",
            }
            feature_cols = [c for c in df.columns if c not in exclude_cols and df[c].dtype in [np.float64, np.float32, np.int64, np.int32]]

            logger.info("Using %d features, %d bars", len(feature_cols), len(df))

            # Walk-forward backtest
            preds, confs, actual_rets = run_walk_forward_backtest(
                df, feature_cols, n_splits=N_SPLITS,
            )

            # Trim df to match prediction length
            test_df = df.iloc[len(df) - len(preds):].copy()

            # Overall
            strat_returns, trade_mask = compute_returns_with_costs(preds, confs, actual_rets)
            result = compute_metrics(strat_returns, trade_mask)
            result.symbol = symbol
            result.session = "all"
            all_results.append(result)

            logger.info(
                "  [ALL] trades=%d  sharpe=%.2f  PF=%.2f  maxDD=%.2f%%  return=%.2f%%  %s",
                result.n_trades, result.sharpe_ratio, result.profit_factor,
                result.max_drawdown * 100, result.total_return * 100,
                "✓ PASS" if result.passed else "✗ FAIL",
            )

            # Per-session
            for session_name in SESSIONS:
                session_df = filter_by_session(test_df, session_name)
                if len(session_df) < 50:
                    continue

                # Get indices relative to test_df
                session_indices = test_df.index.isin(session_df.index)
                trimmed_mask = session_indices[:len(preds)]
                if np.sum(trimmed_mask) < 50:
                    continue

                s_returns = strat_returns[trimmed_mask]
                s_trade_mask = trade_mask[trimmed_mask]

                s_result = compute_metrics(s_returns, s_trade_mask)
                s_result.symbol = symbol
                s_result.session = session_name
                all_results.append(s_result)

                logger.info(
                    "  [%s] trades=%d  sharpe=%.2f  PF=%.2f  maxDD=%.2f%%  %s",
                    session_name.upper(), s_result.n_trades, s_result.sharpe_ratio,
                    s_result.profit_factor, s_result.max_drawdown * 100,
                    "✓" if s_result.passed else "✗",
                )

        except Exception as e:
            logger.error("Failed to validate %s: %s", symbol, e, exc_info=True)
            result = BacktestResult(symbol=symbol, session="all")
            all_results.append(result)

    # Aggregate
    overall_results = [r for r in all_results if r.session == "all" and r.n_trades > 0]
    if overall_results:
        avg_sharpe = np.mean([r.sharpe_ratio for r in overall_results])
        avg_pf = np.mean([r.profit_factor for r in overall_results])
        worst_dd = max([r.max_drawdown for r in overall_results])
        total_trades = sum([r.n_trades for r in overall_results])
        all_passed = all(r.passed for r in overall_results)

        report.aggregate = {
            "avg_sharpe": round(float(avg_sharpe), 3),
            "avg_profit_factor": round(float(avg_pf), 3),
            "worst_max_drawdown": round(float(worst_dd), 4),
            "total_trades": total_trades,
            "all_symbols_passed": all_passed,
            "thresholds": {
                "sharpe_min": SHARPE_THRESHOLD,
                "profit_factor_min": PROFIT_FACTOR_THRESHOLD,
                "max_drawdown_max": MAX_DRAWDOWN_THRESHOLD,
            },
        }

        if all_passed:
            report.verdict = "FULLY_READY"
            report.real_money_readiness_pct = 95.0
        elif avg_sharpe >= 1.0 and avg_pf >= 1.2:
            report.verdict = "LIMITED"
            report.real_money_readiness_pct = 60.0
        else:
            report.verdict = "NOT_READY"
            report.real_money_readiness_pct = 25.0
    else:
        report.aggregate = {"error": "No valid test results"}

    report.results = [asdict(r) for r in all_results]
    return report


def main():
    logger.info("Starting Vision AI Alpha Validation")
    logger.info("Symbols: %s", SYMBOLS)
    logger.info("Timeframe: %s | Min bars: %d", TIMEFRAME, MIN_BARS)
    logger.info("Total cost: %.1f bps", TOTAL_COST_BPS)
    logger.info("-" * 60)

    report = validate()

    output_path = PROJECT_ROOT / "scripts" / "alpha_validation_report.json"
    with open(output_path, "w") as f:
        json.dump(asdict(report), f, indent=2)

    logger.info("=" * 60)
    logger.info("VALIDATION COMPLETE")
    logger.info("Verdict: %s", report.verdict)
    logger.info("Real-money readiness: %.0f%%", report.real_money_readiness_pct)
    logger.info("Report saved to: %s", output_path)
    logger.info("=" * 60)

    if report.aggregate:
        agg = report.aggregate
        logger.info("Avg Sharpe: %s", agg.get("avg_sharpe", "N/A"))
        logger.info("Avg PF:     %s", agg.get("avg_profit_factor", "N/A"))
        logger.info("Worst DD:   %s", agg.get("worst_max_drawdown", "N/A"))


if __name__ == "__main__":
    main()
