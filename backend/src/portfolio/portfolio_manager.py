"""
Portfolio manager: tracks positions, P&L, equity, and integrates optimization.

Supports state persistence via StateManager for crash recovery.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, List, Optional

from backend.src.portfolio.optimizer import KellyCriterion

if TYPE_CHECKING:
    pass

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
        self.equity_timestamps: List[str] = [datetime.now(timezone.utc).isoformat()]

        self.realized_pnl = 0.0
        self.total_trades = 0
        self.winning_trades = 0

        # Position sizing
        self.kelly = KellyCriterion(max_fraction=0.15, half_kelly=True)

    # --------------------------------------------------
    # Position Management
    # --------------------------------------------------

    def open_position(
        self,
        symbol: str,
        quantity: float,
        price: float,
        side="long",
        strategy_name: str = "",
        metadata: Optional[Dict] = None,
    ):

        if symbol in self.positions:
            # We can scale in, but for strictness let's just add to quantity
            pos = self.positions[symbol]
            old_qty = pos["quantity"]
            old_price = pos["entry_price"]
            new_qty = old_qty + quantity
            avg_price = ((old_qty * old_price) + (quantity * price)) / new_qty
            pos["quantity"] = new_qty
            pos["entry_price"] = avg_price
            cost = quantity * price
            self.cash -= cost
            logger.info("Scaled into %s %s @ %.2f (Total: %.6f)", side, symbol, price, new_qty)
            return

        cost = quantity * price

        if cost > self.cash:
            # Scale down to available cash
            quantity = (self.cash * 0.99) / price
            cost = quantity * price
            if quantity <= 0:
                raise ValueError("Not enough cash to open position")
                
        self.cash -= cost

        self.positions[symbol] = {
            "quantity": quantity,
            "entry_price": price,
            "side": side,
            "entry_time": datetime.now(timezone.utc).isoformat(),
            "unrealized_pnl": 0.0,
            "max_drawn": price, # track for trailing stops
            "strategy_name": strategy_name or "",
            "metadata": metadata or {},
        }

        logger.info("Opened %s %.6f %s @ %.2f", side, quantity, symbol, price)

    def close_position(self, symbol: str, price: float, close_quantity: Optional[float] = None):

        if symbol not in self.positions:
            return None

        position = self.positions[symbol]
        total_quantity = position["quantity"]
        
        qty_to_close = close_quantity if close_quantity is not None and close_quantity < total_quantity else total_quantity
        
        entry_price = position["entry_price"]
        side = position["side"]

        # Calculate PnL on the closed portion
        if side == "long":
            pnl = (price - entry_price) * qty_to_close
            self.cash += qty_to_close * price
        else:
            pnl = (entry_price - price) * qty_to_close
            self.cash += (entry_price * qty_to_close) + pnl

        self.realized_pnl += pnl
        
        is_full_close = (qty_to_close >= total_quantity * 0.99)
        
        if is_full_close:
            self.total_trades += 1
            if pnl > 0:
                self.winning_trades += 1
            self.positions.pop(symbol)
            action = "Closed"
        else:
            self.positions[symbol]["quantity"] -= qty_to_close
            action = "Partially Closed"

        trade_record = {
            "symbol": symbol,
            "entry_price": entry_price,
            "exit_price": price,
            "quantity": qty_to_close,
            "side": side,
            "pnl": round(pnl, 2),
            "pnl_pct": (
                round(pnl / (entry_price * qty_to_close) * 100, 2) if entry_price > 0 else 0
            ),
            "entry_time": position.get("entry_time", ""),
            "exit_time": datetime.now(timezone.utc).isoformat(),
            "strategy_name": position.get("strategy_name", ""),
            "metadata": position.get("metadata", {}),
            "partial": not is_full_close
        }

        self.trade_history.append(trade_record)

        logger.info("%s %s %s @ %.2f — PnL: %.2f", action, side, symbol, price, pnl)
        return trade_record

    # --------------------------------------------------
    # Equity Tracking
    # --------------------------------------------------

    def update_equity(self, market_prices: Dict[str, float], current_time: Optional[datetime] = None):

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
        
        # Track daily equity reset
        dt = current_time or datetime.now(timezone.utc)
        current_date_str = dt.strftime("%Y-%m-%d")
        
        if getattr(self, "current_date", None) != current_date_str:
            self.current_date = current_date_str
            self.daily_starting_equity = equity
            
        self.equity_timestamps.append(dt.isoformat())

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
        win_rate = (
            self.winning_trades / self.total_trades if self.total_trades > 0 else 0
        )

        total_return = (
            (self.equity_curve[-1] - self.initial_cash) / self.initial_cash
            if self.equity_curve
            else 0
        )

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
            "current_equity": (
                round(self.equity_curve[-1], 2)
                if self.equity_curve
                else self.initial_cash
            ),
        }

    def get_rolling_metrics(self, n_trades: int = 50) -> Dict[str, float]:
        """Calculate performance over the most recent N trades."""
        recent_trades = self.trade_history[-n_trades:] if self.trade_history else []
        if not recent_trades:
            return {"sharpe": 0.0, "win_rate": 0.0, "drawdown": 0.0}

        wins = [t for t in recent_trades if t.get("pnl", 0) > 0]
        win_rate = len(wins) / len(recent_trades) if recent_trades else 0.0

        import numpy as np
        pnl_pcts = [t.get("pnl_pct", 0) for t in recent_trades]
        
        if len(pnl_pcts) > 2:
            std_dev = np.std(pnl_pcts)
            sharpe = (np.mean(pnl_pcts) / std_dev) if std_dev > 1e-6 else 0.0
        else:
            sharpe = 0.0

        # Calculate localized drawdown from recent equity points corresponding to these trades
        # As an approximation, we can calculate drawdown on a simulated equity series built from these trades
        sim_equity = np.zeros(len(pnl_pcts) + 1)
        sim_equity[0] = 100.0  # start at 100%
        for i, pct in enumerate(pnl_pcts):
            sim_equity[i+1] = sim_equity[i] * (1 + pct / 100.0)
            
        cummax = np.maximum.accumulate(sim_equity)
        drawdown = (sim_equity - cummax) / (cummax + 1e-10)
        max_dd = float(abs(drawdown.min())) if len(drawdown) > 0 else 0.0

        return {
            "sharpe": round(sharpe, 4),
            "win_rate": round(win_rate, 4),
            "drawdown": round(max_dd, 4),
        }

    def get_strategy_performance(self, strategy_name: str, regime: str = "") -> Dict[str, float]:
        """Calculate win rate and profit factor for a specific strategy & regime."""
        trades = [t for t in self.trade_history if t.get("strategy_name") == strategy_name]
        if regime:
            trades = [t for t in trades if t.get("metadata", {}).get("regime") == regime]
            
        if not trades:
            return {"score": 1.0, "win_rate": 0.0}
            
        wins = [t for t in trades if t.get("pnl", 0) > 0]
        losses = [t for t in trades if t.get("pnl", 0) <= 0]
        win_rate = len(wins) / len(trades)
        
        gross_profit = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 2.0
        
        # Performance score (1.0 is neutral, >1 is good, <1 is bad)
        score = (win_rate * 2) * min(profit_factor, 3.0)
        return {"score": max(0.5, min(score, 2.0)), "win_rate": win_rate}

    # --------------------------------------------------
    # Portfolio State
    # --------------------------------------------------

    def get_portfolio(self) -> Dict:

        unrealized = sum(
            pos.get("unrealized_pnl", 0) for pos in self.positions.values()
        )
        current_equity = self.cash + unrealized + sum(pos["quantity"] * pos["entry_price"] for pos in self.positions.values())
        
        # Calculate daily PNL (assuming daily_start_equity is tracked)
        # We can approximate daily PnL by tracking realized + unrealized relative to a daily high watermark,
        # but for now we'll use a simplified daily_pnl against initial_cash if daily_starting_equity isn't set, 
        # or properly track it in update_equity.
        daily_pnl = current_equity - getattr(self, "daily_starting_equity", self.initial_cash)
        
        # Calculate max dropdown efficiently
        import numpy as np
        if len(self.equity_curve) > 1:
            eq_arr = np.array(self.equity_curve)
            cummax = np.maximum.accumulate(eq_arr)
            drawdowns = (eq_arr - cummax) / (cummax + 1e-10)
            max_dd = float(abs(drawdowns.min()))
        else:
            max_dd = 0.0

        return {
            "cash": round(self.cash, 2),
            "positions": self.positions,
            "trade_history": self.trade_history[-20:],  # last 20 trades
            "equity_curve": self.equity_curve[-100:],  # last 100 points
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(unrealized, 2),
            "open_trades": len(self.positions),
            "total_trades": self.total_trades,
            "daily_pnl": daily_pnl,  # True daily PNL for risk limit checks
            "max_drawdown": max_dd,
        }

    # --------------------------------------------------
    # State Serialization (for crash recovery)
    # --------------------------------------------------

    def to_dict(self) -> Dict:
        """Serialize full portfolio state for persistence."""
        return {
            "initial_cash": self.initial_cash,
            "cash": self.cash,
            "positions": self.positions,
            "trade_history": self.trade_history[-100:],
            "equity_curve": self.equity_curve[-200:],
            "realized_pnl": self.realized_pnl,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "PortfolioManager":
        """Restore portfolio from serialized state."""
        pm = cls(initial_cash=data.get("initial_cash", 10000))
        pm.cash = data.get("cash", pm.initial_cash)
        pm.positions = data.get("positions", {})
        pm.trade_history = data.get("trade_history", [])
        pm.equity_curve = data.get("equity_curve", [pm.initial_cash])
        pm.realized_pnl = data.get("realized_pnl", 0.0)
        pm.total_trades = data.get("total_trades", 0)
        pm.winning_trades = data.get("winning_trades", 0)
        logger.info("Portfolio restored: cash={pm.cash:.2f}, trades=%s", pm.total_trades)
        return pm
