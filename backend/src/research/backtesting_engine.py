"""
Backtesting engine for discrete signals (1=long, -1=short, 0=flat).
Produces trades, equity curve, and comprehensive performance metrics.

Metrics:
  - Sharpe ratio, Sortino ratio, Calmar ratio
  - Maximum drawdown, profit factor
  - Expected value per trade
  - Monte Carlo confidence intervals
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

# ------------------------------------------------
# Convert probabilities to signals
# ------------------------------------------------


def probabilities_to_signals(
    proba: np.ndarray,
    long_threshold: float = 0.55,
    short_threshold: float = 0.45,
) -> np.ndarray:

    proba = np.asarray(proba).ravel()

    signals = np.zeros(len(proba))

    signals[proba >= long_threshold] = 1
    signals[proba <= short_threshold] = -1

    return signals


# ------------------------------------------------
# Trade object
# ------------------------------------------------


@dataclass
class Trade:
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    side: str
    pnl: float
    pnl_pct: float


# ------------------------------------------------
# Backtest result
# ------------------------------------------------


@dataclass
class BacktestResult:
    total_return: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    expected_value: float
    num_trades: int

    trades: List[Trade] = field(default_factory=list)
    equity_curve: np.ndarray = field(default_factory=lambda: np.array([]))
    trades_pnl: np.ndarray = field(default_factory=lambda: np.array([]))


# ------------------------------------------------
# Backtest engine
# ------------------------------------------------


class BacktestEngine:

    def __init__(
        self,
        initial_capital: float = 100000.0,
        commission_pct: float = 0.0015,
        position_size_pct: float = 1.0,
        spread_bps: float = 8.0,
        slippage_bps: float = 6.0,
        latency_bps: float = 2.0,
        stop_loss_pct: float = 0.01,
        rr_target: float = 3.5,
    ):
        self.initial_capital = initial_capital
        self.commission_pct = commission_pct
        self.position_size_pct = position_size_pct
        self.spread_bps = spread_bps
        self.slippage_bps = slippage_bps
        self.latency_bps = latency_bps
        self.stop_loss_pct = stop_loss_pct
        self.rr_target = rr_target

    def run(
        self, df: pd.DataFrame, signals: np.ndarray, price_col="close"
    ) -> BacktestResult:

        df = df.copy()

        signals = np.asarray(signals).ravel()

        # Align signals with dataframe
        df["Signal"] = np.pad(signals, (0, max(0, len(df) - len(signals))))[: len(df)]

        df["Returns"] = df[price_col].pct_change().fillna(0)

        capital = self.initial_capital
        position = 0

        entry_price = None
        entry_date = None
        stop_price = None
        take_profit_price = None
        extreme_price = None

        equity_curve = [capital]
        trades: List[Trade] = []

        for i in range(1, len(df)):

            signal = df["Signal"].iloc[i]
            price = float(df[price_col].iloc[i])
            date = str(df.index[i])[:10]

            half_spread = (self.spread_bps / 10000.0) * 0.5
            impact = (self.slippage_bps + self.latency_bps) / 10000.0

            exec_buy = price * (1.0 + half_spread + impact)
            exec_sell = price * (1.0 - half_spread - impact)

            # Manage existing position with stop/target/trailing before flips.
            if position != 0:
                if position > 0:
                    extreme_price = max(extreme_price or exec_sell, exec_sell)
                    r_now = (exec_sell - entry_price) / max(entry_price - stop_price, 1e-8)
                    if r_now >= 2.0:
                        trailing = extreme_price * (1.0 - 0.012)
                        stop_price = max(stop_price, trailing)
                    exit_price = None
                    if exec_sell <= stop_price:
                        exit_price = stop_price
                    elif exec_sell >= take_profit_price:
                        exit_price = take_profit_price
                else:
                    extreme_price = min(extreme_price or exec_buy, exec_buy)
                    r_now = (entry_price - exec_buy) / max(stop_price - entry_price, 1e-8)
                    if r_now >= 2.0:
                        trailing = extreme_price * (1.0 + 0.012)
                        stop_price = min(stop_price, trailing)
                    exit_price = None
                    if exec_buy >= stop_price:
                        exit_price = stop_price
                    elif exec_buy <= take_profit_price:
                        exit_price = take_profit_price

                # Forced exit on opposite signal.
                if signal == -position:
                    exit_price = exec_sell if position > 0 else exec_buy

                if exit_price is not None:
                    pnl_pct = (exit_price - entry_price) / entry_price * position
                    gross_pnl = capital * self.position_size_pct * pnl_pct
                    fee = abs(capital * self.position_size_pct) * self.commission_pct
                    pnl = gross_pnl - fee
                    capital += pnl

                    trades.append(
                        Trade(
                            entry_date=entry_date,
                            exit_date=date,
                            entry_price=entry_price,
                            exit_price=exit_price,
                            side="long" if position > 0 else "short",
                            pnl=pnl,
                            pnl_pct=pnl_pct * 100,
                        )
                    )

                    position = 0
                    entry_price = None
                    entry_date = None
                    stop_price = None
                    take_profit_price = None
                    extreme_price = None

            # Open new position
            if position == 0 and signal != 0:
                position = signal
                entry_price = exec_buy if position > 0 else exec_sell
                entry_date = date
                initial_risk = entry_price * self.stop_loss_pct
                if position > 0:
                    stop_price = entry_price - initial_risk
                    take_profit_price = entry_price + (initial_risk * self.rr_target)
                    extreme_price = entry_price
                else:
                    stop_price = entry_price + initial_risk
                    take_profit_price = entry_price - (initial_risk * self.rr_target)
                    extreme_price = entry_price

                capital -= abs(capital * self.position_size_pct) * self.commission_pct

            # Mark-to-market equity update.
            if position != 0:
                ret = df["Returns"].iloc[i] * position
                capital *= 1 + ret

            equity_curve.append(capital)

        equity = np.array(equity_curve)
        returns = np.diff(equity) / (equity[:-1] + 1e-12)

        # --------------------------------------------------
        # Performance metrics
        # --------------------------------------------------

        # Periods per year (auto-detect from data frequency)
        if len(df) > 1:
            dt = pd.Series(df.index).diff().median()
            if hasattr(dt, "total_seconds"):
                secs = dt.total_seconds()
                if secs <= 0:
                    secs = 300  # default 5min
            else:
                secs = 86400  # default daily
            periods_per_year = 365.25 * 24 * 3600 / secs
        else:
            periods_per_year = 252

        # Sharpe ratio
        if len(returns) > 0 and np.std(returns) > 0:
            sharpe = float(
                np.mean(returns) / np.std(returns) * np.sqrt(periods_per_year)
            )
        else:
            sharpe = 0.0

        # Sortino ratio (downside deviation only)
        downside_returns = returns[returns < 0]
        if len(downside_returns) > 0 and np.std(downside_returns) > 0:
            sortino = float(
                np.mean(returns) / np.std(downside_returns) * np.sqrt(periods_per_year)
            )
        else:
            sortino = 0.0

        # Total return
        total_return = (equity[-1] - self.initial_capital) / self.initial_capital

        # Max drawdown
        cummax = np.maximum.accumulate(equity)
        drawdown = (equity - cummax) / cummax
        max_dd = float(drawdown.min())

        # Calmar ratio (annualized return / max drawdown)
        n_periods = len(equity) - 1
        if n_periods > 0 and abs(max_dd) > 0:
            years = n_periods / periods_per_year
            ann_return = (equity[-1] / equity[0]) ** (1 / max(years, 1e-6)) - 1
            calmar = float(ann_return / abs(max_dd))
        else:
            calmar = 0.0

        # Trade metrics
        trades_pnl = np.array([t.pnl for t in trades])

        wins = [t for t in trades if t.pnl > 0]
        win_rate = len(wins) / len(trades) if trades else 0

        gross_profit = trades_pnl[trades_pnl > 0].sum() if len(trades_pnl) else 0
        gross_loss = abs(trades_pnl[trades_pnl < 0].sum()) if len(trades_pnl) else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        # Expected value per trade
        expected_value = float(trades_pnl.mean()) if len(trades_pnl) > 0 else 0

        return BacktestResult(
            total_return=total_return,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            max_drawdown=max_dd,
            win_rate=win_rate,
            profit_factor=profit_factor,
            expected_value=expected_value,
            num_trades=len(trades),
            trades=trades,
            equity_curve=equity,
            trades_pnl=trades_pnl,
        )

    def run_from_symbol(
        self, symbol: str, period: str = "1y", price_col: str = "close"
    ) -> dict:
        """Convenience: fetch data, add features, generate simple signals, run backtest."""

        from backend.src.data.fetcher import DataFetcher
        from backend.src.features.indicators import FeatureEngineer

        fetcher = DataFetcher()
        df = fetcher.fetch(symbol)

        engineer = FeatureEngineer()
        df = engineer.add_all_indicators(df)
        df = df.dropna()

        # Simple RSI signals as baseline
        signals = np.zeros(len(df))
        if "RSI" in df.columns:
            signals[df["RSI"] < 30] = 1
            signals[df["RSI"] > 70] = -1

        result = self.run(df, signals, price_col)

        return {
            "total_return": result.total_return,
            "sharpe_ratio": result.sharpe_ratio,
            "sortino_ratio": result.sortino_ratio,
            "calmar_ratio": result.calmar_ratio,
            "max_drawdown": result.max_drawdown,
            "win_rate": result.win_rate,
            "profit_factor": result.profit_factor,
            "expected_value": result.expected_value,
            "num_trades": result.num_trades,
            "trades": [t.__dict__ for t in result.trades[-50:]],
        }

    # --------------------------------------------------
    # Monte Carlo simulation
    # --------------------------------------------------

    def monte_carlo(
        self, trades_pnl: np.ndarray, n_simulations: int = 1000, n_trades: int = 100
    ) -> dict:
        """
        Bootstrap trades to estimate confidence intervals.

        Returns:
            {
                median_return, p5_return, p95_return,
                prob_profitable, median_max_dd
            }
        """
        if len(trades_pnl) < 5:
            return {"error": "Not enough trades for Monte Carlo"}

        final_returns = []
        max_drawdowns = []

        for _ in range(n_simulations):
            # Sample with replacement
            sampled = np.random.choice(trades_pnl, size=n_trades, replace=True)
            equity = np.cumsum(sampled) + self.initial_capital

            final_ret = (equity[-1] - self.initial_capital) / self.initial_capital
            final_returns.append(final_ret)

            cummax = np.maximum.accumulate(equity)
            dd = ((equity - cummax) / cummax).min()
            max_drawdowns.append(dd)

        final_returns = np.array(final_returns)
        max_drawdowns = np.array(max_drawdowns)

        return {
            "median_return": round(float(np.median(final_returns)), 4),
            "p5_return": round(float(np.percentile(final_returns, 5)), 4),
            "p95_return": round(float(np.percentile(final_returns, 95)), 4),
            "prob_profitable": round(float(np.mean(final_returns > 0)), 4),
            "median_max_dd": round(float(np.median(max_drawdowns)), 4),
            "p5_max_dd": round(float(np.percentile(max_drawdowns, 5)), 4),
            "n_simulations": n_simulations,
        }

    # --------------------------------------------------
    # Walk-Forward Validation
    # --------------------------------------------------

    def walk_forward_validation(
        self,
        df: pd.DataFrame,
        signals: np.ndarray,
        n_splits: int = 5,
        train_ratio: float = 0.7,
        price_col: str = "close",
    ) -> dict:
        """
        Walk-forward out-of-sample validation.

        Splits data into rolling train/test windows. Runs backtest on each
        test window. Aggregates out-of-sample metrics.

        Args:
            df: full DataFrame with OHLCV data
            signals: signal array covering entire df
            n_splits: number of walk-forward windows
            train_ratio: fraction of each window used for training
            price_col: price column name

        Returns:
            Aggregated out-of-sample metrics across all windows.
        """
        n = len(df)
        if n < 100:
            return {"error": "Not enough data for walk-forward validation"}

        signals = np.asarray(signals).ravel()
        if len(signals) != n:
            signals = np.pad(signals, (0, max(0, n - len(signals))))[:n]

        window_size = n // n_splits
        if window_size < 20:
            return {"error": "Window size too small"}

        results = []

        for i in range(n_splits):
            start = i * window_size
            end = min(start + window_size, n)

            if end - start < 20:
                continue

            train_end = start + int((end - start) * train_ratio)
            test_start = train_end
            test_end = end

            if test_end - test_start < 5:
                continue

            # Run backtest on test (out-of-sample) portion only
            test_df = df.iloc[test_start:test_end].copy()
            test_signals = signals[test_start:test_end]

            try:
                result = self.run(test_df, test_signals, price_col)
                results.append(
                    {
                        "window": i + 1,
                        "test_start": str(test_df.index[0])[:10],
                        "test_end": str(test_df.index[-1])[:10],
                        "total_return": result.total_return,
                        "sharpe_ratio": result.sharpe_ratio,
                        "sortino_ratio": result.sortino_ratio,
                        "max_drawdown": result.max_drawdown,
                        "win_rate": result.win_rate,
                        "num_trades": result.num_trades,
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "window": i + 1,
                        "error": str(e),
                    }
                )

        if not results:
            return {"error": "No valid windows produced results"}

        # Aggregate out-of-sample metrics
        valid = [r for r in results if "error" not in r]
        if not valid:
            return {"windows": results, "error": "All windows failed"}

        return {
            "n_windows": len(valid),
            "avg_return": round(float(np.mean([r["total_return"] for r in valid])), 4),
            "avg_sharpe": round(float(np.mean([r["sharpe_ratio"] for r in valid])), 4),
            "avg_sortino": round(
                float(np.mean([r["sortino_ratio"] for r in valid])), 4
            ),
            "avg_max_drawdown": round(
                float(np.mean([r["max_drawdown"] for r in valid])), 4
            ),
            "avg_win_rate": round(float(np.mean([r["win_rate"] for r in valid])), 4),
            "total_trades": sum(r["num_trades"] for r in valid),
            "windows": results,
        }

    def walk_forward_retrain_validation(
        self,
        df: pd.DataFrame,
        feature_cols: Optional[List[str]] = None,
        target_col: str = "Target_Direction",
        n_splits: int = 5,
        train_ratio: float = 0.7,
        price_col: str = "close",
        long_threshold: float = 0.55,
        short_threshold: float = 0.45,
        model_factory: Optional[Callable[[], object]] = None,
    ) -> Dict:
        """
        Leakage-safe walk-forward validation with retraining per window.

        For each rolling window:
          1) Train model on historical subset only.
          2) Generate out-of-sample probabilities on test subset.
          3) Convert probabilities to signals and backtest test subset only.

        This avoids reusing precomputed full-sample signals and prevents
        train/test contamination in signal generation.
        """
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.metrics import (accuracy_score, f1_score, precision_score,
                                     recall_score, roc_auc_score)

        n = len(df)
        if n < 120:
            return {"error": "Not enough data for strict walk-forward retraining"}

        if target_col not in df.columns:
            return {"error": f"Target column '{target_col}' not found"}

        clean_df = df.copy()
        if feature_cols is None:
            excluded = {"Target", "Target_Direction", target_col}
            feature_cols = [c for c in clean_df.columns if c not in excluded]

        missing_features = [c for c in feature_cols if c not in clean_df.columns]
        if missing_features:
            return {"error": f"Missing feature columns: {missing_features[:10]}"}

        if model_factory is None:

            def model_factory():
                return RandomForestClassifier(
                    n_estimators=300,
                    max_depth=8,
                    min_samples_leaf=10,
                    class_weight="balanced",
                    random_state=42,
                    n_jobs=-1,
                )

        window_size = n // n_splits
        if window_size < 30:
            return {"error": "Window size too small for retraining"}

        results: List[Dict] = []

        for i in range(n_splits):
            start = i * window_size
            end = min(start + window_size, n)

            if end - start < 30:
                continue

            train_end = start + int((end - start) * train_ratio)
            test_start = train_end
            test_end = end

            if test_end - test_start < 10:
                continue

            train_df = clean_df.iloc[start:train_end].copy()
            test_df = clean_df.iloc[test_start:test_end].copy()

            try:
                X_train = (
                    train_df[feature_cols]
                    .replace([np.inf, -np.inf], np.nan)
                    .fillna(0.0)
                    .values
                )
                y_train = train_df[target_col].astype(int).values

                X_test = (
                    test_df[feature_cols]
                    .replace([np.inf, -np.inf], np.nan)
                    .fillna(0.0)
                    .values
                )
                y_test = test_df[target_col].astype(int).values

                model = model_factory()
                model.fit(X_train, y_train)

                proba = model.predict_proba(X_test)[:, 1]
                y_pred = (proba >= 0.5).astype(int)

                test_signals = probabilities_to_signals(
                    proba,
                    long_threshold=long_threshold,
                    short_threshold=short_threshold,
                )

                bt_result = self.run(test_df, test_signals, price_col)

                cls = {
                    "accuracy": float(accuracy_score(y_test, y_pred)),
                    "precision": float(
                        precision_score(y_test, y_pred, zero_division=0)
                    ),
                    "recall": float(recall_score(y_test, y_pred, zero_division=0)),
                    "f1": float(f1_score(y_test, y_pred, zero_division=0)),
                    "roc_auc": (
                        float(roc_auc_score(y_test, proba))
                        if len(np.unique(y_test)) > 1
                        else 0.5
                    ),
                }

                results.append(
                    {
                        "window": i + 1,
                        "train_start": str(train_df.index[0])[:10],
                        "train_end": str(train_df.index[-1])[:10],
                        "test_start": str(test_df.index[0])[:10],
                        "test_end": str(test_df.index[-1])[:10],
                        "classification": cls,
                        "trading": {
                            "total_return": bt_result.total_return,
                            "sharpe_ratio": bt_result.sharpe_ratio,
                            "sortino_ratio": bt_result.sortino_ratio,
                            "max_drawdown": bt_result.max_drawdown,
                            "win_rate": bt_result.win_rate,
                            "num_trades": bt_result.num_trades,
                        },
                    }
                )

            except Exception as e:
                results.append({"window": i + 1, "error": str(e)})

        valid = [r for r in results if "error" not in r]
        if not valid:
            return {
                "error": "All strict walk-forward windows failed",
                "windows": results,
            }

        return {
            "n_windows": len(valid),
            "avg_classification": {
                "accuracy": round(
                    float(np.mean([r["classification"]["accuracy"] for r in valid])), 4
                ),
                "precision": round(
                    float(np.mean([r["classification"]["precision"] for r in valid])), 4
                ),
                "recall": round(
                    float(np.mean([r["classification"]["recall"] for r in valid])), 4
                ),
                "f1": round(
                    float(np.mean([r["classification"]["f1"] for r in valid])), 4
                ),
                "roc_auc": round(
                    float(np.mean([r["classification"]["roc_auc"] for r in valid])), 4
                ),
            },
            "avg_trading": {
                "return": round(
                    float(np.mean([r["trading"]["total_return"] for r in valid])), 4
                ),
                "sharpe": round(
                    float(np.mean([r["trading"]["sharpe_ratio"] for r in valid])), 4
                ),
                "sortino": round(
                    float(np.mean([r["trading"]["sortino_ratio"] for r in valid])), 4
                ),
                "max_drawdown": round(
                    float(np.mean([r["trading"]["max_drawdown"] for r in valid])), 4
                ),
                "win_rate": round(
                    float(np.mean([r["trading"]["win_rate"] for r in valid])), 4
                ),
                "total_trades": int(sum(r["trading"]["num_trades"] for r in valid)),
            },
            "windows": results,
        }
