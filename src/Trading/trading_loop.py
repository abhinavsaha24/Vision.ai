"""
Paper trading loop with metrics tracking and trade logging.

Features:
  - Simulated order execution
  - Real-time P&L tracking
  - Performance metrics per cycle
  - Exit condition monitoring (stop loss, trailing stop, take profit)
"""

from __future__ import annotations

import time
import logging
from datetime import datetime
from typing import Dict, Optional

from src.data_collection.fetcher import DataFetcher
from src.feature_engineering.indicators import FeatureEngineer
from src.prediction.predictor import Predictor
from src.strategy.strategy_engine import StrategyEngine
from src.Risk_manager.risk_manager import RiskManager
from src.Execution.execution_engine import ExecutionEngine
from src.Portfolio.portfolio_manager import PortfolioManager
from src.regime.regime_detector import MarketRegimeDetector

logger = logging.getLogger(__name__)


class TradingLoop:
    """
    Autonomous paper trading loop.
    Runs cycles of: fetch → predict → signal → risk → execute → track.
    """

    def __init__(self, symbol: str = "BTC/USDT", initial_cash: float = 10000):

        self.symbol = symbol
        self.running = False
        self.cycle_count = 0

        # Components
        self.fetcher = DataFetcher()
        self.engineer = FeatureEngineer()
        self.predictor = None
        self.strategy = StrategyEngine()
        self.risk = RiskManager()
        self.portfolio = PortfolioManager(initial_cash=initial_cash)
        self.regime_detector = MarketRegimeDetector()

        self.execution = ExecutionEngine(
            strategy_engine=self.strategy,
            risk_manager=self.risk,
            portfolio_manager=self.portfolio,
        )

        # Performance tracking
        self.highest_prices: Dict[str, float] = {}
        self.cycle_results = []

        # Try loading predictor
        try:
            self.predictor = Predictor()
            logger.info("Predictor loaded for paper trading")
        except Exception as e:
            logger.warning(f"Predictor not available: {e}")

    # --------------------------------------------------
    # Single cycle
    # --------------------------------------------------

    def run_cycle(self) -> Dict:
        """Run one trading cycle."""

        self.cycle_count += 1
        cycle_time = datetime.utcnow().isoformat()

        logger.info(f"\n{'='*50}")
        logger.info(f"Cycle {self.cycle_count} | {cycle_time}")
        logger.info(f"{'='*50}")

        try:
            # 1. Fetch market data
            df = self.fetcher.fetch(self.symbol)
            df = self.engineer.add_all_indicators(df)
            df = df.dropna()

            if len(df) < 50:
                return {"status": "INSUFFICIENT_DATA", "cycle": self.cycle_count}

            price = float(df["close"].iloc[-1])

            # Track highest price for trailing stops
            self.highest_prices[self.symbol] = max(
                self.highest_prices.get(self.symbol, 0), price
            )

            # 2. Detect regime
            regime = self.regime_detector.get_regime(df)

            # 3. Get AI prediction
            prediction = {"probability": 0.5, "direction": "NEUTRAL"}
            if self.predictor:
                preds = self.predictor.predict_symbol(self.symbol, horizon=1)
                if preds:
                    prediction = preds[0]

            # 4. Check exit conditions for open positions
            exit_reason = self.execution.check_exit_conditions(
                self.symbol, price, self.highest_prices.get(self.symbol, price)
            )

            if exit_reason:
                logger.info(f"Exit triggered: {exit_reason}")
                self.portfolio.close_position(self.symbol, price)
                self.highest_prices.pop(self.symbol, None)

            # 5. Execute trade pipeline
            result = self.execution.process_market_data(
                symbol=self.symbol,
                df=df,
                prediction=prediction,
                price=price,
                regime=regime,
            )

            # 6. Update portfolio equity
            self.portfolio.update_equity({self.symbol: price})

            # 7. Log metrics
            performance = self.portfolio.get_performance()
            portfolio_state = self.portfolio.get_portfolio()

            cycle_result = {
                "cycle": self.cycle_count,
                "timestamp": cycle_time,
                "price": round(price, 2),
                "prediction": prediction,
                "regime": regime,
                "execution": result,
                "exit_trigger": exit_reason,
                "equity": round(portfolio_state["equity_curve"][-1], 2) if portfolio_state["equity_curve"] else 0,
                "cash": round(portfolio_state["cash"], 2),
                "open_trades": portfolio_state["open_trades"],
                "total_trades": performance["total_trades"],
                "win_rate": round(performance["win_rate"], 4),
                "total_return": round(performance["total_return"], 4),
            }

            self.cycle_results.append(cycle_result)

            # Keep only last 1000 results
            if len(self.cycle_results) > 1000:
                self.cycle_results = self.cycle_results[-500:]

            logger.info(f"Price: {price:.2f} | Signal: {result.get('status')} | "
                        f"Equity: {cycle_result['equity']:.2f} | "
                        f"Return: {performance['total_return']:.2%}")

            return cycle_result

        except Exception as e:
            logger.error(f"Trading cycle error: {e}")
            return {"status": "ERROR", "error": str(e), "cycle": self.cycle_count}

    # --------------------------------------------------
    # Continuous loop
    # --------------------------------------------------

    def start(self, interval_seconds: int = 300):
        """Start continuous paper trading."""
        self.running = True
        logger.info(f"\n🚀 Vision-AI Paper Trading Started | {self.symbol}\n")

        while self.running:
            self.run_cycle()
            time.sleep(interval_seconds)

    def stop(self):
        """Stop paper trading."""
        self.running = False
        logger.info("Paper trading stopped")

    # --------------------------------------------------
    # Status / Metrics
    # --------------------------------------------------

    def get_status(self) -> Dict:
        """Get current paper trading status."""
        performance = self.portfolio.get_performance()
        portfolio_state = self.portfolio.get_portfolio()

        return {
            "running": self.running,
            "symbol": self.symbol,
            "cycle_count": self.cycle_count,
            "performance": performance,
            "portfolio": {
                "cash": portfolio_state["cash"],
                "open_trades": portfolio_state["open_trades"],
                "positions": portfolio_state["positions"],
            },
            "recent_cycles": self.cycle_results[-10:],
        }