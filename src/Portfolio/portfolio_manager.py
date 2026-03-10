from typing import Dict, List


class PortfolioManager:

    def __init__(self, initial_cash: float = 10000):

        self.cash = initial_cash
        self.positions: Dict = {}

        self.trade_history: List[Dict] = []

        self.equity_curve: List[float] = [initial_cash]

        self.realized_pnl = 0


    def open_position(self, symbol: str, quantity: float, price: float, side="long"):

        if symbol in self.positions:
            raise ValueError("Position already open")

        cost = quantity * price

        if side == "long":

            if cost > self.cash:
                raise ValueError("Not enough cash")

            self.cash -= cost

        self.positions[symbol] = {
            "quantity": quantity,
            "entry_price": price,
            "side": side
        }


    def close_position(self, symbol: str, price: float):

        if symbol not in self.positions:
            return

        position = self.positions.pop(symbol)

        quantity = position["quantity"]
        entry_price = position["entry_price"]
        side = position["side"]

        if side == "long":

            value = quantity * price
            pnl = value - (quantity * entry_price)

            self.cash += value

        else:

            pnl = (entry_price - price) * quantity
            self.cash += (entry_price * quantity) + pnl

        self.realized_pnl += pnl

        self.trade_history.append({
            "symbol": symbol,
            "entry_price": entry_price,
            "exit_price": price,
            "quantity": quantity,
            "side": side,
            "pnl": pnl
        })


    def update_equity(self, market_prices: Dict[str, float]):

        equity = self.cash

        for symbol, pos in self.positions.items():

            price = market_prices.get(symbol)

            if price is not None:

                if pos["side"] == "long":
                    equity += pos["quantity"] * price
                else:
                    equity += pos["quantity"] * (2 * pos["entry_price"] - price)

        self.equity_curve.append(equity)


    def get_portfolio(self):

        return {
            "cash": self.cash,
            "positions": self.positions,
            "trade_history": self.trade_history,
            "equity_curve": self.equity_curve,
            "realized_pnl": self.realized_pnl,
            "open_trades": len(self.positions)
        }