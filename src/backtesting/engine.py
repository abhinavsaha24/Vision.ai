"""
Backtesting engine for discrete signals (1=long, -1=short, 0=flat).
Produces trades, equity curve, and performance metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

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
    max_drawdown: float
    win_rate: float
    profit_factor: float
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


    def run(self, df: pd.DataFrame, signals: np.ndarray, price_col="close"):

        df = df.copy()

        signals = np.asarray(signals).ravel()

        # align signals with dataframe
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

            # close position
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

            # open new position
            if position == 0 and signal != 0:

                position = signal
                entry_price = price
                entry_date = date

                capital -= capital * self.commission_pct

            # update equity
            if position != 0:

                ret = df["Returns"].iloc[i] * position

                capital *= (1 + ret)

            equity_curve.append(capital)

        equity = np.array(equity_curve)

        returns = np.diff(equity) / (equity[:-1] + 1e-12)

        # Sharpe ratio (5-minute candles)
        periods_per_year = 365 * 24 * 12

        sharpe = (
            float(np.mean(returns) / (np.std(returns) + 1e-12) * np.sqrt(periods_per_year))
            if len(returns) > 0
            else 0
        )

        total_return = (equity[-1] - self.initial_capital) / self.initial_capital

        cummax = np.maximum.accumulate(equity)

        drawdown = (equity - cummax) / cummax

        max_dd = float(drawdown.min())

        wins = [t for t in trades if t.pnl > 0]

        win_rate = len(wins) / len(trades) if trades else 0

        trades_pnl = np.array([t.pnl for t in trades])

        gross_profit = trades_pnl[trades_pnl > 0].sum() if len(trades_pnl) else 0
        gross_loss = abs(trades_pnl[trades_pnl < 0].sum()) if len(trades_pnl) else 0

        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        return BacktestResult(
            total_return=total_return,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            win_rate=win_rate,
            profit_factor=profit_factor,
            num_trades=len(trades),
            trades=trades,
            equity_curve=equity,
            trades_pnl=trades_pnl,
        )


def run_from_symbol(self, symbol: str, period: str = "1y", price_col: str = "close"):

    from src.data_collection.fetcher import DataFetcher
    from src.feature_engineering.indicators import FeatureEngineer

    fetcher = DataFetcher()

    df = fetcher.fetch(symbol)

    engineer = FeatureEngineer()

    df = engineer.add_all_indicators(df)

    df = df.dropna()

    signals = np.zeros(len(df))

    if "RSI" in df.columns:
        signals[df["RSI"] < 30] = 1
        signals[df["RSI"] > 70] = -1

    result = self.run(df, signals, price_col)

    return {
        "total_return": result.total_return,
        "sharpe_ratio": result.sharpe_ratio,
        "max_drawdown": result.max_drawdown,
        "win_rate": result.win_rate,
        "num_trades": result.num_trades,
        "trades": [t.__dict__ for t in result.trades],
    }