"""Standalone trading worker entrypoint for dedicated worker deployments."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Support direct execution: python backend/src/workers/trading_worker.py
if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parents[3]
    project_root_str = str(project_root)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)

load_dotenv(dotenv_path=Path(__file__).resolve().parents[3] / ".env")

from backend.src.core.config import settings
from backend.src.core.structured_logger import setup_logging
from backend.src.monitoring.execution_metrics_collector import \
    ExecutionMetricsCollector
from backend.src.workers.trading_loop import TradingLoop
from backend.src.workers.worker_manager import WorkerManager

setup_logging()
logger = logging.getLogger("vision-ai.trading-worker")


async def main() -> None:
    symbols_env = os.getenv("TRADING_SYMBOLS", settings.default_symbol)
    symbols = [symbol.strip() for symbol in symbols_env.split(",") if symbol.strip()]
    initial_cash = float(
        os.getenv(
            "PAPER_TRADING_INITIAL_CASH", str(settings.paper_trading_initial_cash)
        )
    )
    interval_seconds = int(
        os.getenv("POLLING_INTERVAL_SECONDS", str(settings.paper_trading_interval))
    )

    metrics = ExecutionMetricsCollector(window_size=100)
    worker = TradingLoop(
        symbol=symbols[0] if symbols else settings.default_symbol,
        symbols=symbols,
        initial_cash=initial_cash,
        metrics_collector=metrics,
    )
    worker.interval_seconds = interval_seconds

    manager = WorkerManager()
    manager.register("paper_trading", worker, auto_restart=True, max_restarts=10)

    logger.info(
        "Starting standalone trading worker | symbols=%s interval=%ss",
        symbols,
        interval_seconds,
    )

    await manager.start_all()

    try:
        while True:
            await asyncio.sleep(30)
            logger.info("Worker status: %s", manager.get_status())
    except asyncio.CancelledError:
        raise
    finally:
        await manager.stop_all()


if __name__ == "__main__":
    asyncio.run(main())
