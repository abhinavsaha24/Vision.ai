"""
Trading loop: autonomous trading cycle supporting both paper and live modes.

Features:
  - Simulated order execution (paper mode)
  - Real exchange execution (live mode via ExchangeAdapter)
  - Real-time P&L tracking
  - Performance metrics per cycle
  - Exit condition monitoring (stop loss, trailing stop, take profit)
  - Graceful reconnection on network failures
  - Heartbeat monitoring
"""

from __future__ import annotations

import time
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from backend.src.data.fetcher import DataFetcher
from backend.src.features.indicators import FeatureEngineer
from backend.src.models.predictor import Predictor
from backend.src.strategy.strategy_engine import StrategyEngine
from backend.src.risk.risk_manager import RiskManager
from backend.src.execution.execution_engine import ExecutionEngine
from backend.src.portfolio.portfolio_manager import PortfolioManager
from backend.src.models.regime_detector import MarketRegimeDetector
from backend.src.exchange.exchange_adapter import ExchangeAdapter, PaperAdapter

logger = logging.getLogger(__name__)


class TradingLoop:
    """
    Autonomous trading loop.
    Runs cycles of: fetch → predict → signal → risk → execute → track.

    Supports both paper and live execution via ExchangeAdapter.
    """

    def __init__(self, symbol: str = "BTC/USDT",
                 initial_cash: float = 10000,
                 adapter: Optional[ExchangeAdapter] = None):

        self.symbol = symbol
        self.running = False
        self.cycle_count = 0
        self.last_heartbeat = time.time()

        # Components
        self.fetcher = DataFetcher()
        self.engineer = FeatureEngineer()
        self.predictor = None
        self.strategy = StrategyEngine()
        self.risk = RiskManager()
        self.portfolio = PortfolioManager(initial_cash=initial_cash)
        self.regime_detector = MarketRegimeDetector()

        # Exchange adapter (paper by default)
        if adapter is None:
            adapter = PaperAdapter(
                initial_cash=initial_cash,
                commission_rate=0.001,
                max_slippage=0.001,
            )
        self.adapter = adapter
        self.mode = "paper" if isinstance(adapter, PaperAdapter) else "live"

        self.execution = ExecutionEngine(
            strategy_engine=self.strategy,
            risk_manager=self.risk,
            portfolio_manager=self.portfolio,
            adapter=adapter,
        )

        # Performance tracking
        self.highest_prices: Dict[str, float] = {}
        self.cycle_results = []
        self.consecutive_errors = 0
        self.max_consecutive_errors = 10

        # Try loading predictor
        try:
            self.predictor = Predictor()
            logger.info("Predictor loaded for trading")
        except Exception as e:
            logger.warning(f"Predictor not available: {e}")

    # --------------------------------------------------
    # Single cycle
    # --------------------------------------------------

    def run_cycle(self) -> Dict:
        """Run one trading cycle."""

        self.cycle_count += 1
        self.last_heartbeat = time.time()
        cycle_time = datetime.now(timezone.utc).isoformat()

        logger.info(f"\n{'='*50}")
        logger.info(f"[{self.mode.upper()}] Cycle {self.cycle_count} | {cycle_time}")
        logger.info(f"{'='*50}")

        try:
            # 1. Fetch market data (with retry)
            df = self._fetch_with_retry(self.symbol)
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
                "mode": self.mode,
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

            # Reset consecutive errors on success
            self.consecutive_errors = 0

            logger.info(f"Price: {price:.2f} | Signal: {result.get('status')} | "
                        f"Equity: {cycle_result['equity']:.2f} | "
                        f"Return: {performance['total_return']:.2%}")

            return cycle_result

        except Exception as e:
            self.consecutive_errors += 1
            logger.error(f"Trading cycle error ({self.consecutive_errors}/{self.max_consecutive_errors}): {e}")

            if self.consecutive_errors >= self.max_consecutive_errors:
                logger.critical(
                    f"Max consecutive errors reached ({self.max_consecutive_errors}). "
                    f"Activating kill switch."
                )
                self.risk.activate_kill_switch("Max consecutive errors")
                self.running = False

            return {"status": "ERROR", "error": str(e), "cycle": self.cycle_count}

    # --------------------------------------------------
    # Data fetch with retry
    # --------------------------------------------------

    def _fetch_with_retry(self, symbol: str, max_retries: int = 3, delay: float = 5.0):
        """Fetch market data with retry on failure."""
        for attempt in range(max_retries):
            try:
                return self.fetcher.fetch(symbol)
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Data fetch attempt {attempt + 1} failed: {e}, retrying in {delay}s")
                    time.sleep(delay)
                else:
                    raise

    # --------------------------------------------------
    # Continuous loop
    # --------------------------------------------------

    def start(self, interval_seconds: int = 300):
        """Start continuous trading."""
        self.running = True
        logger.info(f"\n🚀 Vision-AI {self.mode.upper()} Trading Started | {self.symbol}\n")

        while self.running:
            self.run_cycle()
            time.sleep(interval_seconds)

    def stop(self):
        """Stop trading."""
        self.running = False
        logger.info(f"{self.mode.upper()} trading stopped")

    # --------------------------------------------------
    # Status / Metrics
    # --------------------------------------------------

    def get_status(self) -> Dict:
        """Get current trading status."""
        performance = self.portfolio.get_performance()
        portfolio_state = self.portfolio.get_portfolio()
        order_stats = self.execution.get_order_statistics()

        return {
            "running": self.running,
            "mode": self.mode,
            "symbol": self.symbol,
            "cycle_count": self.cycle_count,
            "consecutive_errors": self.consecutive_errors,
            "last_heartbeat": self.last_heartbeat,
            "performance": performance,
            "orders": order_stats,
            "portfolio": {
                "cash": portfolio_state["cash"],
                "open_trades": portfolio_state["open_trades"],
                "positions": portfolio_state["positions"],
            },
            "recent_cycles": self.cycle_results[-10:],
        }