"""
Backtesting engine: runs strategy with discrete signals (1=long, -1=short, 0=hold)
and returns performance plus equity curve and trade PnLs for metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd


def probabilities_to_signals(
    proba: np.ndarray,
    long_threshold: float = 0.55,
    short_threshold: float = 0.45,
) -> np.ndarray:
    """
    Convert ensemble P(class=1) to trading signals.
    proba >= long_threshold -> 1 (long), proba <= short_threshold -> -1 (short), else 0.
    """
    proba = np.asarray(proba).ravel()
    signals = np.zeros(len(proba), dtype=np.float64)
    signals[proba >= long_threshold] = 1
    signals[proba <= short_threshold] = -1
    return signals


@dataclass
class Trade:
    """Single closed trade."""

    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    side: str
    pnl: float
    pnl_pct: float


@dataclass
class BacktestResult:
    """Backtest output: metrics, trades, equity curve and trade PnLs for reporting."""

    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    num_trades: int
    trades: List[Trade] = field(default_factory=list)
    equity_curve: np.ndarray = field(default_factory=lambda: np.array([]))
    trades_pnl: np.ndarray = field(default_factory=lambda: np.array([]))


class BacktestEngine:
    """Event-style backtester: signals 1=long, -1=short, 0=no position."""

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        commission_pct: float = 0.001,
        position_size_pct: float = 1.0,
    ) -> None:
        self.initial_capital = initial_capital
        self.commission_pct = commission_pct
        self.position_size_pct = position_size_pct

    def run(
        self,
        df: pd.DataFrame,
        signals: np.ndarray,
        price_col: str = "close",
    ) -> BacktestResult:
        """
        Run backtest. signals: 1=long, -1=short, 0=hold.
        Returns BacktestResult with equity_curve and trades_pnl for compute_trading_metrics.
        """
        df = df.copy()
        sig = np.asarray(signals, dtype=float).ravel()[: len(df)]
        df["Signal"] = np.pad(sig, (0, max(0, len(df) - len(sig))), constant_values=0)
        df["Returns"] = df[price_col].astype(float).pct_change().fillna(0)

        capital = self.initial_capital
        position = 0.0
        trades: List[Trade] = []
        equity_curve: List[float] = [capital]

        for i in range(1, len(df)):
            prev_signal = df["Signal"].iloc[i - 1]
            curr_signal = df["Signal"].iloc[i]
            price = float(df[price_col].iloc[i])
            prev_price = float(df[price_col].iloc[i - 1])
            date_str = str(df.index[i])[:10]

            if prev_signal != curr_signal:
                if prev_signal != 0:
                    exit_price = prev_price
                    pnl_pct = (price / exit_price - 1.0) * prev_signal
                    pnl = position * pnl_pct - abs(position) * self.commission_pct * 2.0
                    capital += pnl
                    trades.append(
                        Trade(
                            entry_date="",
                            exit_date=date_str,
                            entry_price=exit_price,
                            exit_price=price,
                            side="long" if prev_signal > 0 else "short",
                            pnl=pnl,
                            pnl_pct=pnl_pct * 100.0,
                        )
                    )
                    position = 0.0

                if curr_signal != 0:
                    position = capital * self.position_size_pct * curr_signal
                    capital -= abs(position) * self.commission_pct

            if position != 0:
                ret = df["Returns"].iloc[i]
                capital += position * ret
                position *= 1.0 + ret

            equity_curve.append(capital)

        if position != 0:
            last_ret = (df[price_col].iloc[-1] / df[price_col].iloc[-2] - 1.0) * np.sign(position)
            capital += position * last_ret

        equity = np.array(equity_curve)
        returns = np.diff(equity) / (equity[:-1] + 1e-12)
        returns = returns[~np.isnan(returns)]

        total_return = (capital - self.initial_capital) / self.initial_capital
        sharpe = (
            float(np.mean(returns) / np.std(returns) * np.sqrt(252))
            if len(returns) > 0 and np.std(returns) > 0
            else 0.0
        )
        cummax = np.maximum.accumulate(equity)
        drawdowns = (equity - cummax) / (cummax + 1e-12)
        max_dd = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0
        wins = [t for t in trades if t.pnl > 0]
        win_rate = len(wins) / len(trades) if trades else 0.0
        trades_pnl = np.array([t.pnl for t in trades])

        return BacktestResult(
            total_return=total_return,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            win_rate=win_rate,
            num_trades=len(trades),
            trades=trades,
            equity_curve=equity,
            trades_pnl=trades_pnl,
        )

    def run_from_symbol(
        self,
        symbol: str,
        period: str = "1y",
        price_col: str = "close",
    ) -> dict:
        """
        Fetch data, build features, generate RSI-based signals, run backtest.
        Kept for API compatibility; pipeline uses model predictions instead.
        """
        from src.data_collection.fetcher import DataFetcher
        from src.feature_engineering.indicators import FeatureEngineer

        fetcher = DataFetcher()
        df = fetcher.fetch(symbol, period=period)
        engineer = FeatureEngineer()
        df = engineer.add_all_indicators(df)
        df = df.dropna(subset=["Target_Direction"])
        signals = np.zeros(len(df))
        if "RSI" in df.columns:
            signals[df["RSI"] < 30] = 1
            signals[df["RSI"] > 70] = -1
        result = self.run(df, signals, price_col=price_col)
        return {
            "total_return": result.total_return,
            "sharpe_ratio": result.sharpe_ratio,
            "max_drawdown": result.max_drawdown,
            "win_rate": result.win_rate,
            "num_trades": result.num_trades,
            "trades": [
                {
                    "entry_date": t.entry_date,
                    "exit_date": t.exit_date,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "side": t.side,
                    "pnl": t.pnl,
                    "pnl_pct": t.pnl_pct,
                }
                for t in result.trades
            ],
        }
