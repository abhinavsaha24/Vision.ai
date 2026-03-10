import time
import datetime

from src.data_collection.fetcher import DataFetcher
from src.feature_engineering.indicators import FeatureEngineer
from src.prediction.predictor import Predictor
from src.strategy.strategy_engine import StrategyEngine
from src.risk.risk_manager import RiskManager
from src.execution.execution_engine import ExecutionEngine
from src.portfolio.portfolio_manager import PortfolioManager


class TradingLoop:

    def __init__(self, symbol="BTC/USDT"):

        self.symbol = symbol

        self.fetcher = DataFetcher()
        self.engineer = FeatureEngineer()

        self.predictor = Predictor()

        self.strategy = StrategyEngine()
        self.risk = RiskManager()

        self.portfolio = PortfolioManager(initial_cash=10000)

        self.execution = ExecutionEngine(
            strategy_engine=self.strategy,
            risk_manager=self.risk,
            portfolio_manager=self.portfolio
        )

    def run_cycle(self):

        print("\n==============================")
        print("Cycle:", datetime.datetime.utcnow())
        print("==============================")

        try:

            # 1️⃣ Fetch market data
            df = self.fetcher.fetch(self.symbol)

            df = self.engineer.add_all_indicators(df)

            df = df.dropna()

            # 2️⃣ Get AI prediction
            predictions = self.predictor.predict_symbol(self.symbol, horizon=1)

            if not predictions:
                print("No prediction generated")
                return

            prediction = predictions[0]

            print("Prediction:", prediction)

            # 3️⃣ Current market price
            price = float(df["close"].iloc[-1])

            # 4️⃣ Execute trade pipeline
            result = self.execution.process_market_data(
                symbol=self.symbol,
                df=df,
                prediction=prediction,
                price=price
            )

            print("Execution:", result)

            # 5️⃣ Update portfolio equity
            self.portfolio.update_equity({
                self.symbol: price
            })

            print("Portfolio:", self.portfolio.get_portfolio())

        except Exception as e:

            print("Trading cycle error:", e)

    def start(self):

        print("\nVision-AI Trading Engine Started\n")

        while True:

            self.run_cycle()

            # 5-minute cycle (Binance candle timeframe)
            time.sleep(300)