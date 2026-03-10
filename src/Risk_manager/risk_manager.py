from dataclasses import dataclass
from typing import Dict


@dataclass
class RiskLimits:

    max_position_size: float = 0.02
    max_daily_loss: float = 0.05
    max_drawdown: float = 0.20
    max_open_trades: int = 5


class RiskManager:

    def __init__(self, limits: RiskLimits = RiskLimits()):

        self.limits = limits


    def calculate_position_size(self, capital: float, price: float) -> float:

        if capital <= 0 or price <= 0:
            return 0

        risk_amount = capital * self.limits.max_position_size

        size = risk_amount / price

        return size


    def check_position_size(self, portfolio: Dict, trade_value: float) -> bool:

        capital = portfolio.get("cash", 0)

        if capital <= 0:
            return False

        size_ratio = trade_value / capital

        return size_ratio <= self.limits.max_position_size


    def check_drawdown(self, portfolio: Dict) -> bool:

        equity = portfolio.get("equity_curve", [])

        if len(equity) == 0:
            return True

        peak = max(equity)

        if peak == 0:
            return True

        current = equity[-1]

        drawdown = (peak - current) / peak

        return drawdown <= self.limits.max_drawdown


    def check_daily_loss(self, portfolio: Dict) -> bool:

        daily_pnl = portfolio.get("daily_pnl", 0)

        capital = portfolio.get("cash", 0)

        if capital <= 0:
            return False

        loss_ratio = abs(daily_pnl) / capital

        return loss_ratio <= self.limits.max_daily_loss


    def check_open_trades(self, portfolio: Dict) -> bool:

        open_trades = portfolio.get("open_trades", 0)

        return open_trades < self.limits.max_open_trades


    def approve_trade(self, portfolio: Dict, trade_value: float) -> bool:

        if not self.check_position_size(portfolio, trade_value):
            return False

        if not self.check_drawdown(portfolio):
            return False

        if not self.check_daily_loss(portfolio):
            return False

        if not self.check_open_trades(portfolio):
            return False

        return True