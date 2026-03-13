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
from typing import List, Optional

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
        commission_pct: float = 0.001,
        position_size_pct: float = 1.0,
    ):
        self.initial_capital = initial_capital
        self.commission_pct = commission_pct
        self.position_size_pct = position_size_pct

    def run(self, df: pd.DataFrame, signals: np.ndarray, price_col="close") -> BacktestResult:

        df = df.copy()

        signals = np.asarray(signals).ravel()

        # Align signals with dataframe
        df["Signal"] = np.pad(signals, (0, max(0, len(df) - len(signals))))[:len(df)]

        df["Returns"] = df[price_col].pct_change().fillna(0)

        capital = self.initial_capital
        position = 0

        entry_price = None
        entry_date = None

        equity_curve = [capital]
        trades: List[Trade] = []

        for i in range(1, len(df)):

            signal = df["Signal"].iloc[i]
            price = float(df[price_col].iloc[i])
            date = str(df.index[i])[:10]

            # Close position
            if position != 0 and signal != position:

                pnl_pct = (price - entry_price) / entry_price * position
                pnl = capital * self.position_size_pct * pnl_pct
                pnl -= abs(pnl) * self.commission_pct

                capital += pnl

                trades.append(
                    Trade(
                        entry_date=entry_date,
                        exit_date=date,
                        entry_price=entry_price,
                        exit_price=price,
                        side="long" if position > 0 else "short",
                        pnl=pnl,
                        pnl_pct=pnl_pct * 100,
                    )
                )

                position = 0
                entry_price = None
                entry_date = None

            # Open new position
            if position == 0 and signal != 0:
                position = signal
                entry_price = price
                entry_date = date
                capital -= capital * self.commission_pct

            # Update equity
            if position != 0:
                ret = df["Returns"].iloc[i] * position
                capital *= (1 + ret)

            equity_curve.append(capital)

        equity = np.array(equity_curve)
        returns = np.diff(equity) / (equity[:-1] + 1e-12)

        # --------------------------------------------------
        # Performance metrics
        # --------------------------------------------------

        # Periods per year (auto-detect from data frequency)
        if len(df) > 1:
            dt = pd.Series(df.index).diff().median()
            if hasattr(dt, 'total_seconds'):
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
            sharpe = float(np.mean(returns) / np.std(returns) * np.sqrt(periods_per_year))
        else:
            sharpe = 0.0

        # Sortino ratio (downside deviation only)
        downside_returns = returns[returns < 0]
        if len(downside_returns) > 0 and np.std(downside_returns) > 0:
            sortino = float(np.mean(returns) / np.std(downside_returns) * np.sqrt(periods_per_year))
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

    def run_from_symbol(self, symbol: str, period: str = "1y",
                        price_col: str = "close") -> dict:
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

    def monte_carlo(self, trades_pnl: np.ndarray, n_simulations: int = 1000,
                    n_trades: int = 100) -> dict:
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