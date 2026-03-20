"""
Trading loop: autonomous trading cycle supporting both paper and live modes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from backend.src.core.cache import RedisCache
from backend.src.core.config import settings
from backend.src.data.fetcher import DataFetcher
from backend.src.database.db import get_connection, release_connection
from backend.src.exchange.exchange_adapter import ExchangeAdapter, PaperAdapter
from backend.src.execution.execution_engine import ExecutionEngine
from backend.src.features.indicators import FeatureEngineer
from backend.src.models.predictor import Predictor
from backend.src.models.regime_detector import MarketRegimeDetector
from backend.src.models.meta_alpha_engine import MetaAlphaEngine
from backend.src.portfolio.portfolio_manager import PortfolioManager
from backend.src.risk.risk_manager import RiskManager
from backend.src.strategy.strategy_engine import StrategyEngine

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# -------------------------------------------------------
# Database persistence helpers
# -------------------------------------------------------


def _persist_signal(signal: Dict):
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO signals
            (symbol, direction, confidence, probability, regime, strategy, position_size)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                signal.get("symbol", ""),
                signal.get("direction", "HOLD"),
                signal.get("confidence", 0.5),
                signal.get("probability", 0.5),
                signal.get("regime", ""),
                signal.get("strategy", ""),
                signal.get("position_size", 0),
            ),
        )

        conn.commit()
        cur.close()
        release_connection(conn)

    except Exception as e:
        if "DATABASE_URL" in str(e):
            logger.debug("Signal persistence skipped: %s", e)
            return
        logger.error("Signal persistence error: %s", e)


def _persist_equity(cash: float, equity: float, positions_value: float = 0):
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO equity_history (equity, cash, positions_value)
            VALUES (%s,%s,%s)
            """,
            (equity, cash, positions_value),
        )

        conn.commit()
        cur.close()
        release_connection(conn)

    except Exception as e:
        if "DATABASE_URL" in str(e):
            logger.debug("Equity persistence skipped: %s", e)
            return
        logger.warning("Equity persist failed: %s", e)


def _persist_portfolio_snapshot(perf: Dict, portfolio: Dict):
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO portfolio_snapshots
            (cash, equity, unrealized_pnl, realized_pnl,
             open_trades, total_trades, win_rate, max_drawdown)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                portfolio.get("cash", 0),
                perf.get("current_equity", 0),
                portfolio.get("unrealized_pnl", 0),
                portfolio.get("realized_pnl", 0),
                portfolio.get("open_trades", 0),
                perf.get("total_trades", 0),
                perf.get("win_rate", 0),
                perf.get("max_drawdown", 0),
            ),
        )

        conn.commit()
        cur.close()
        release_connection(conn)

    except Exception as e:
        if "DATABASE_URL" in str(e):
            logger.debug("Portfolio snapshot persistence skipped: %s", e)
            return
        logger.warning("Portfolio snapshot persist failed: %s", e)


# -------------------------------------------------------
# Trading Loop
# -------------------------------------------------------


class TradingLoop:

    def __init__(
        self,
        symbol: str = "BTC/USDT",
        initial_cash: float = 10000,
        adapter: Optional[ExchangeAdapter] = None,
        metrics_collector: Optional[Any] = None,
        symbols: Optional[list[str]] = None,
    ):

        self.symbols = list(symbols or [symbol])
        self.symbol = self.symbols[0]
        self.running = False
        self.cycle_count = 0
        self.last_heartbeat = time.time()
        self.interval_seconds = int(settings.paper_trading_interval)
        self.metrics_collector = metrics_collector

        self.fetcher = DataFetcher()
        self.engineer = FeatureEngineer()
        self.predictor: Optional[Predictor] = None
        self.strategy = StrategyEngine()
        self.risk = RiskManager()
        self.portfolio = PortfolioManager(initial_cash=initial_cash)
        self.regime_detector = MarketRegimeDetector()
        self.meta_alpha = MetaAlphaEngine()

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

        self._cache = RedisCache(
            url=settings.redis_url,
            default_ttl=settings.redis_ttl,
            enabled=settings.redis_enabled,
        )

        self.highest_prices: Dict[str, float] = {}
        self.cycle_results = []
        self.max_symbol_concurrency = 4
        self.symbol_timeout_seconds = 30.0
        self.max_retries = 3
        self.base_retry_delay_seconds = 0.5
        self.total_errors = 0
        self.last_error: Optional[str] = None

        try:
            self.predictor = Predictor()
            logger.info("Predictor loaded")
        except Exception as e:
            logger.warning("Predictor unavailable: %s", e)

    # -------------------------------------------------------

    async def _retry_async(
        self,
        op_name: str,
        op: Callable[[], Awaitable[Any]],
        retries: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        attempts = retries if retries is not None else self.max_retries
        delay = self.base_retry_delay_seconds
        last_exc: Optional[Exception] = None

        for attempt in range(1, attempts + 1):
            try:
                if timeout:
                    return await asyncio.wait_for(op(), timeout=timeout)
                return await op()
            except Exception as exc:
                last_exc = exc
                if attempt >= attempts:
                    break
                logger.warning(
                    "%s failed (attempt %s/%s): %s",
                    op_name,
                    attempt,
                    attempts,
                    exc,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 5.0)

        raise RuntimeError(f"{op_name} failed after {attempts} attempts: {last_exc}")

    async def run_cycle(self):
        self.cycle_count += 1
        self.last_heartbeat = time.time()
        cycle_time = datetime.now(timezone.utc).isoformat()

        logger.info("Cycle %s | %s | symbols=%s", self.cycle_count, cycle_time, self.symbols)

        await asyncio.to_thread(self._publish_heartbeat, cycle_time)

        sem = asyncio.Semaphore(max(1, self.max_symbol_concurrency))

        async def guarded_symbol_cycle(active_symbol: str):
            async with sem:
                return await self._run_symbol_cycle(active_symbol, cycle_time)

        tasks = [guarded_symbol_cycle(active_symbol) for active_symbol in self.symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for symbol, result in zip(self.symbols, results):
            if isinstance(result, Exception):
                self.total_errors += 1
                self.last_error = f"{symbol}: {result}"
                logger.error("Symbol cycle failed for %s: %s", symbol, result)

    async def _run_symbol_cycle(self, symbol: str, cycle_time: str):
        try:

            async def fetch_df():
                return await asyncio.to_thread(self.fetcher.fetch, symbol)

            df = await self._retry_async(
                op_name=f"fetch[{symbol}]",
                op=fetch_df,
                timeout=self.symbol_timeout_seconds,
            )

            df = await asyncio.to_thread(self.engineer.add_all_indicators, df)
            df = await asyncio.to_thread(df.dropna)

            if len(df) < 50:
                return

            price = float(df["close"].iloc[-1])

            regime = await asyncio.to_thread(self.regime_detector.get_regime, df)

            prediction = {"probability": 0.5, "direction": "NEUTRAL", "confidence": 0.5}

            if self.predictor:
                preds = await asyncio.to_thread(
                    self.predictor.predict_symbol, symbol, 1
                )
                if preds:
                    prediction = preds[0]

            normalized_symbol = symbol.replace("/", "").replace("-", "").upper()
            market_snapshot = await asyncio.to_thread(
                self._cache.get_json,
                f"market:snapshot:{normalized_symbol}",
            )

            sentiment_score = 0.0
            strategy_result = {
                "score": float(prediction.get("confidence", 0.5) or 0.5) - 0.5,
            }
            meta_alpha = await asyncio.to_thread(
                self.meta_alpha.infer,
                prediction,
                strategy_result,
                sentiment_score,
                regime,
                market_snapshot or {},
            )
            prediction["meta_alpha"] = meta_alpha
            prediction["signal"] = meta_alpha.get("signal", "HOLD")
            prediction["confidence"] = float(meta_alpha.get("confidence", prediction.get("confidence", 0.5)) or 0.5)

            async def process_market_data():
                return await asyncio.to_thread(
                    self.execution.process_market_data,
                    symbol,
                    df,
                    prediction,
                    price,
                    regime,
                    market_snapshot,
                )

            result = await self._retry_async(
                op_name=f"process_market_data[{symbol}]",
                op=process_market_data,
                timeout=self.symbol_timeout_seconds,
            )

            await asyncio.to_thread(self.portfolio.update_equity, {symbol: price})

            performance = await asyncio.to_thread(self.portfolio.get_performance)
            portfolio_state = await asyncio.to_thread(self.portfolio.get_portfolio)

            equity_val = (
                portfolio_state["equity_curve"][-1]
                if portfolio_state["equity_curve"]
                else 0
            )

            if (
                self.metrics_collector
                and self.execution
                and hasattr(self.execution, "order_manager")
            ):
                try:
                    self.metrics_collector.update_from_order_manager(
                        self.execution.order_manager
                    )
                except Exception as e:
                    logger.debug("Metrics collection error: %s", e)

            signal_data = {
                "symbol": symbol,
                "direction": prediction.get("signal", "HOLD"),
                "confidence": prediction.get("confidence", 0.5),
                "probability": prediction.get("probability", 0.5),
                "alpha_score": (prediction.get("meta_alpha") or {}).get("alpha_score", 0.5),
                "regime": str(regime),
                "market_state": regime.get("market_state", "UNKNOWN") if isinstance(regime, dict) else "UNKNOWN",
                "strategy": result.get("strategy_name", "alpha_model"),
                "price": round(price, 2),
                "equity": round(equity_val, 2),
                "cycle": self.cycle_count,
                "timestamp": cycle_time,
            }

            await asyncio.to_thread(
                self._cache.set_json, f"signal:{symbol}", signal_data, 600
            )
            await asyncio.to_thread(
                self._cache.set_json, "performance:latest", performance, 600
            )
            await asyncio.to_thread(
                self._cache.set_json, "portfolio:latest", portfolio_state, 600
            )

            await asyncio.to_thread(_persist_signal, signal_data)
            await asyncio.to_thread(
                _persist_equity,
                cash=portfolio_state.get("cash", 0),
                equity=performance.get("current_equity", 0),
                positions_value=portfolio_state.get("positions_value", 0),
            )
            await asyncio.to_thread(
                _persist_portfolio_snapshot, performance, portfolio_state
            )

            logger.info("Symbol: %s | Price: %.2f | Signal: %s | Equity: %.2f", symbol, price, result.get("status"), equity_val)

        except Exception as e:
            self.total_errors += 1
            self.last_error = f"{symbol}: {e}"
            logger.error("Trading cycle error for {symbol}: %s", e)

    def _publish_heartbeat(self, cycle_time: str):
        self._cache.set_json(
            "worker:heartbeat",
            {
                "running": self.running,
                "mode": self.mode,
                "symbol": self.symbol,
                "symbols": self.symbols,
                "cycle": self.cycle_count,
                "timestamp": cycle_time,
                "last_heartbeat": self.last_heartbeat,
            },
            ttl=max(settings.redis_ttl, 120),
        )

    # -------------------------------------------------------

    async def start_async(self, interval_seconds: Optional[int] = None):

        if interval_seconds is not None:
            self.interval_seconds = int(interval_seconds)

        self.running = True
        logger.info("Vision-AI %s Trading Started | symbols=%s", self.mode.upper(), self.symbols)

        while self.running:
            cycle_started = time.time()
            try:
                await self._retry_async(
                    op_name="run_cycle",
                    op=self.run_cycle,
                    retries=max(1, self.max_retries),
                    timeout=max(
                        self.symbol_timeout_seconds, float(self.interval_seconds) * 2
                    ),
                )
            except Exception as exc:
                self.total_errors += 1
                self.last_error = str(exc)
                logger.exception("Trading cycle failed irrecoverably: %s", exc)
                await asyncio.sleep(1.0)
                continue

            elapsed = time.time() - cycle_started
            remaining = max(0.0, float(self.interval_seconds) - elapsed)
            while self.running and remaining > 0:
                sleep_for = min(0.5, remaining)
                await asyncio.sleep(sleep_for)
                remaining -= sleep_for

    def start(self, interval_seconds: int = 60):
        asyncio.run(self.start_async(interval_seconds=interval_seconds))

    def stop(self):
        self.running = False
        self._publish_heartbeat(datetime.now(timezone.utc).isoformat())
        logger.info("Trading stopped")

    def get_status(self) -> Dict:
        return {
            "running": self.running,
            "mode": self.mode,
            "symbol": self.symbol,
            "symbols": self.symbols,
            "cycle_count": self.cycle_count,
            "last_heartbeat": self.last_heartbeat,
            "total_errors": self.total_errors,
            "last_error": self.last_error,
            "portfolio": self.portfolio.get_portfolio(),
            "performance": self.portfolio.get_performance(),
        }


# -------------------------------------------------------
# Run Worker
# -------------------------------------------------------

if __name__ == "__main__":

    loop = TradingLoop(symbol="BTC/USDT")
    loop.start(interval_seconds=60)
