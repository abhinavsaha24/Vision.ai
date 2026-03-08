#!/usr/bin/env python3
"""
End-to-end pipeline:

  1. Fetch data (configurable timeframe, chronological)
  2. Generate features (past-only, no leakage)
  3. Split dataset (time-based, before any fit)
  4. Train models (RF, XGBoost, LightGBM) and ensemble
  5. Generate predictions on test set
  6. Run backtest using model predictions (not RSI rules)
  7. Report classification and trading metrics

Run from project root: python scripts/run_pipeline.py [--symbol AAPL] [--period 1y]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import numpy as np
import pandas as pd

from src.backtesting.engine import BacktestEngine, probabilities_to_signals
from src.data_collection.fetcher import DataFetcher
from src.evaluation.metrics import (
    compute_classification_metrics,
    compute_trading_metrics,
)
from src.feature_engineering.indicators import FeatureEngineer
from src.model_training.trainer import ModelTrainer

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main(
    symbol: str = "AAPL",
    period: str = "1y",
    interval: str = "1d",
    test_size: float = 0.2,
    target_horizon: int = 5,
    long_threshold: float = 0.55,
    short_threshold: float = 0.45,
    initial_capital: float = 100_000.0,
) -> None:
    """Run full pipeline: fetch -> features -> split -> train -> predict -> backtest -> report."""

    logger.info("Pipeline: %s | period=%s | interval=%s", symbol, period, interval)
    print("-" * 60)

    # 1. Fetch data (chronological, clean)
    print("1. Fetching data...")
    fetcher = DataFetcher()
    try:
        df = fetcher.fetch(symbol, period=period, interval=interval)
    except Exception as e:
        logger.error("Fetch failed: %s", e)
        raise
    df = df.sort_index(ascending=True)
    print(f"   Rows: {len(df)}, range: {df.index.min()} to {df.index.max()}")

    # 2. Generate features (past-only; target uses forward return for label only)
    print("2. Generating features...")
    engineer = FeatureEngineer()
    df = engineer.transform(df, column="close", add_target=True, target_horizon=target_horizon)
    # Drop rows with NaN target (last target_horizon rows)
    df = df.dropna(subset=["Target_Direction"])
    print(f"   Feature columns: {len([c for c in df.columns if c not in ('Target', 'Target_Direction')])}")

    # 3. Split dataset by time (no leakage)
    n = len(df)
    split_idx = int(n * (1 - test_size))
    if split_idx < 50:
        split_idx = max(1, n - 100)
    train_df = df.iloc[:split_idx]
    test_df = df.iloc[split_idx:]
    print(f"3. Split: train={len(train_df)}, test={len(test_df)}")

    # 4. Train models (scaler and models on train only)
    print("4. Training models (RF, XGBoost, LightGBM) and ensemble...")
    trainer = ModelTrainer(test_size=test_size)
    trainer.train(train_df, target_col="Target_Direction", run_cv=True)
    trainer.save(f"trading_model_{symbol}")
    print(f"   CV accuracy (mean ± std): {trainer.metrics.get('cv_accuracy_mean', 0):.4f} ± {trainer.metrics.get('cv_accuracy_std', 0):.4f}")
    print(f"   Test accuracy: {trainer.metrics.get('accuracy', 0):.4f}")

    # 5. Predictions on test set (ensemble probabilities)
    X_test = test_df[[c for c in trainer.feature_names_ if c in test_df.columns]].astype(float).values
    X_test_scaled = trainer.scaler.transform(X_test)
    proba = trainer.predict_proba_ensemble(X_test_scaled)
    y_pred = (proba >= 0.5).astype(int)
    y_true = test_df["Target_Direction"].astype(int).values

    # Classification metrics
    clf = compute_classification_metrics(y_true, y_pred)
    print("5. Classification metrics (test set):")
    print(f"   Accuracy:  {clf.accuracy:.4f}")
    print(f"   Precision: {clf.precision:.4f}")
    print(f"   Recall:   {clf.recall:.4f}")
    print(f"   F1:       {clf.f1:.4f}")
    print(f"   Confusion matrix: {clf.confusion_matrix}")

    # 6. Backtest using model predictions (not RSI)
    print("6. Backtesting with model predictions...")
    signals = probabilities_to_signals(proba, long_threshold=long_threshold, short_threshold=short_threshold)
    engine = BacktestEngine(initial_capital=initial_capital)
    result = engine.run(test_df, signals, price_col="close")
    print(f"   Total return: {result.total_return:.2%}")
    print(f"   Sharpe:       {result.sharpe_ratio:.2f}")
    print(f"   Max drawdown: {result.max_drawdown:.2%}")
    print(f"   Win rate:     {result.win_rate:.1%}")
    print(f"   Trades:       {result.num_trades}")

    # 7. Trading metrics (from evaluation module for consistency)
    trading = compute_trading_metrics(result.equity_curve, result.trades_pnl)
    print("7. Trading metrics:")
    print(f"   Sharpe ratio:  {trading.sharpe_ratio:.2f}")
    print(f"   Win rate:      {trading.win_rate:.2%}")
    print(f"   Profit factor: {trading.profit_factor:.2f}")
    print(f"   Max drawdown:  {trading.max_drawdown:.2%}")
    print(f"   Total return:  {trading.total_return:.2%}")
    print(f"   Num trades:    {trading.num_trades}")

    print("-" * 60)
    print("Pipeline complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run AI trading pipeline")
    parser.add_argument("--symbol", "-s", default="AAPL", help="Ticker symbol")
    parser.add_argument("--period", "-p", default="1y", help="Data period (1mo, 3mo, 1y, 2y, etc.)")
    parser.add_argument("--interval", "-i", default="1d", choices=("1d", "1wk", "1mo"), help="Bar interval")
    parser.add_argument("--test-size", type=float, default=0.2, help="Fraction of data for test set")
    parser.add_argument("--target-horizon", type=int, default=5, help="Forward horizon for target (days)")
    parser.add_argument("--long-threshold", type=float, default=0.55, help="Prob threshold for long signal")
    parser.add_argument("--short-threshold", type=float, default=0.45, help="Prob threshold for short signal")
    parser.add_argument("--initial-capital", type=float, default=100_000.0, help="Backtest initial capital")
    args = parser.parse_args()
    main(
        symbol=args.symbol,
        period=args.period,
        interval=args.interval,
        test_size=args.test_size,
        target_horizon=args.target_horizon,
        long_threshold=args.long_threshold,
        short_threshold=args.short_threshold,
        initial_capital=args.initial_capital,
    )
