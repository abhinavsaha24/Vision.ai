from typing import Dict
import datetime


class ExecutionEngine:
    """
    Handles trade execution pipeline:
    Strategy -> Risk -> Portfolio
    """

    def __init__(self, strategy_engine, risk_manager, portfolio_manager):

        self.strategy_engine = strategy_engine
        self.risk_manager = risk_manager
        self.portfolio_manager = portfolio_manager

        # trade configuration
        self.position_size_pct = 0.02
        self.max_slippage = 0.001  # 0.1%


    def process_market_data(self, symbol: str, df, prediction, price: float):

        try:

            # 1️⃣ Generate trading signal
            signal = self.strategy_engine.generate_signal(df, prediction)

            if signal == 0:
                return {"status": "NO_SIGNAL"}

            portfolio = self.portfolio_manager.get_portfolio()

            # 2️⃣ Prevent duplicate positions
            if symbol in portfolio["positions"]:
                return {"status": "POSITION_ALREADY_OPEN"}

            # 3️⃣ Calculate trade value
            capital = portfolio["cash"]

            trade_value = capital * self.position_size_pct

            if trade_value <= 0:
                return {"status": "NO_CAPITAL"}

            # 4️⃣ Risk approval
            if not self.risk_manager.approve_trade(portfolio, trade_value):

                return {"status": "RISK_REJECTED"}

            # 5️⃣ Apply slippage
            execution_price = price * (1 + self.max_slippage)

            quantity = trade_value / execution_price

            # 6️⃣ Execute trade
            if signal == 1:

                self.portfolio_manager.open_position(
                    symbol=symbol,
                    quantity=quantity,
                    price=execution_price,
                    side="long"
                )

                action = "LONG"

            elif signal == -1:

                self.portfolio_manager.open_position(
                    symbol=symbol,
                    quantity=quantity,
                    price=execution_price,
                    side="short"
                )

                action = "SHORT"

            else:

                return {"status": "NO_ACTION"}

            return {
                "status": "TRADE_EXECUTED",
                "symbol": symbol,
                "side": action,
                "price": execution_price,
                "quantity": quantity,
                "timestamp": str(datetime.datetime.utcnow())
            }

        except Exception as e:

            return {
                "status": "EXECUTION_ERROR",
                "error": str(e)
            }