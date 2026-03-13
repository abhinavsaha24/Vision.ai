"""
Portfolio manager: tracks positions, P&L, equity, and integrates optimization.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional
from datetime import datetime

from backend.src.portfolio.optimizer import KellyCriterion

logger = logging.getLogger(__name__)


class PortfolioManager:
    """
    Portfolio management with position tracking, P&L, and history.
    """

    def __init__(self, initial_cash: float = 10000):

        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions: Dict = {}

        self.trade_history: List[Dict] = []
        self.equity_curve: List[float] = [initial_cash]
        self.equity_timestamps: List[str] = [datetime.utcnow().isoformat()]

        self.realized_pnl = 0.0
        self.total_trades = 0
        self.winning_trades = 0

        # Position sizing
        self.kelly = KellyCriterion(max_fraction=0.25, half_kelly=True)

    # --------------------------------------------------
    # Position Management
    # --------------------------------------------------

    def open_position(self, symbol: str, quantity: float, price: float, side="long"):

        if symbol in self.positions:
            raise ValueError(f"Position already open for {symbol}")

        cost = quantity * price

        if side == "long":
            if cost > self.cash:
                raise ValueError("Not enough cash")
            self.cash -= cost

        self.positions[symbol] = {
            "quantity": quantity,
            "entry_price": price,
            "side": side,
            "entry_time": datetime.utcnow().isoformat(),
            "unrealized_pnl": 0.0,
        }

        logger.info(f"Opened {side} {quantity:.6f} {symbol} @ {price:.2f}")

    def close_position(self, symbol: str, price: float):

        if symbol not in self.positions:
            return

        position = self.positions.pop(symbol)

        quantity = position["quantity"]
        entry_price = position["entry_price"]
        side = position["side"]

        if side == "long":
            pnl = (price - entry_price) * quantity
            self.cash += quantity * price
        else:
            pnl = (entry_price - price) * quantity
            self.cash += (entry_price * quantity) + pnl

        self.realized_pnl += pnl
        self.total_trades += 1
        if pnl > 0:
            self.winning_trades += 1

        self.trade_history.append({
            "symbol": symbol,
            "entry_price": entry_price,
            "exit_price": price,
            "quantity": quantity,
            "side": side,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl / (entry_price * quantity) * 100, 2) if entry_price > 0 else 0,
            "entry_time": position.get("entry_time", ""),
            "exit_time": datetime.utcnow().isoformat(),
        })

        logger.info(f"Closed {side} {symbol} @ {price:.2f} — PnL: {pnl:.2f}")

    # --------------------------------------------------
    # Equity Tracking
    # --------------------------------------------------

    def update_equity(self, market_prices: Dict[str, float]):

        equity = self.cash

        for symbol, pos in self.positions.items():
            price = market_prices.get(symbol)
            if price is None:
                continue

            if pos["side"] == "long":
                value = pos["quantity"] * price
                pos["unrealized_pnl"] = value - (pos["quantity"] * pos["entry_price"])
                equity += value
            else:
                unrealized = (pos["entry_price"] - price) * pos["quantity"]
                pos["unrealized_pnl"] = unrealized
                equity += pos["quantity"] * pos["entry_price"] + unrealized

        self.equity_curve.append(equity)
        self.equity_timestamps.append(datetime.utcnow().isoformat())

    # --------------------------------------------------
    # Position Sizing
    # --------------------------------------------------

    def calculate_position_size(self, price: float, confidence: float = 0.5) -> float:
        """Calculate position size using Kelly + confidence."""
        if self.total_trades < 10:
            # Not enough history — use fixed fraction
            return self.cash * 0.02 / price

        win_rate = self.winning_trades / self.total_trades

        # Average win/loss from history
        wins = [t["pnl"] for t in self.trade_history if t["pnl"] > 0]
        losses = [abs(t["pnl"]) for t in self.trade_history if t["pnl"] < 0]

        avg_win = sum(wins) / len(wins) if wins else 1.0
        avg_loss = sum(losses) / len(losses) if losses else 1.0

        kelly_fraction = self.kelly.calculate(win_rate, avg_win, avg_loss)

        # Scale by confidence
        position_fraction = kelly_fraction * confidence

        return self.cash * position_fraction / price

    # --------------------------------------------------
    # Performance Metrics
    # --------------------------------------------------

    def get_performance(self) -> Dict:
        """Calculate performance metrics."""
        win_rate = self.winning_trades / self.total_trades if self.total_trades > 0 else 0

        total_return = (self.equity_curve[-1] - self.initial_cash) / self.initial_cash if self.equity_curve else 0

        # Max drawdown
        import numpy as np
        equity = np.array(self.equity_curve)
        if len(equity) > 1:
            cummax = np.maximum.accumulate(equity)
            drawdown = (equity - cummax) / (cummax + 1e-10)
            max_dd = float(drawdown.min())
        else:
            max_dd = 0.0

        # Profit factor
        wins = [t["pnl"] for t in self.trade_history if t["pnl"] > 0]
        losses = [abs(t["pnl"]) for t in self.trade_history if t["pnl"] < 0]
        gross_profit = sum(wins) if wins else 0
        gross_loss = sum(losses) if losses else 1e-10
        profit_factor = gross_profit / gross_loss

        return {
            "total_return": round(total_return, 4),
            "win_rate": round(win_rate, 4),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "max_drawdown": round(max_dd, 4),
            "profit_factor": round(profit_factor, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "current_equity": round(self.equity_curve[-1], 2) if self.equity_curve else self.initial_cash,
        }

    # --------------------------------------------------
    # Portfolio State
    # --------------------------------------------------

    def get_portfolio(self) -> Dict:

        unrealized = sum(
            pos.get("unrealized_pnl", 0) for pos in self.positions.values()
        )

        return {
            "cash": round(self.cash, 2),
            "positions": self.positions,
            "trade_history": self.trade_history[-20:],  # last 20 trades
            "equity_curve": self.equity_curve[-100:],  # last 100 points
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(unrealized, 2),
            "open_trades": len(self.positions),
            "total_trades": self.total_trades,
            "daily_pnl": 0,  # placeholder for risk manager
        }