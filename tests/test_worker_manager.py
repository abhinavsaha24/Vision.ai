import asyncio

from backend.src.workers.trading_loop import TradingLoop
from backend.src.workers.worker_manager import WorkerManager


class _DummyAsyncWorker:
    def __init__(self):
        self.running = False
        self.started = False
        self.last_heartbeat = 0

    async def start_async(self):
        self.running = True
        self.started = True
        self.last_heartbeat = 1
        while self.running:
            await asyncio.sleep(0.01)

    def stop(self):
        self.running = False


def test_worker_manager_starts_and_stops_async_worker():
    async def run_test():
        manager = WorkerManager()
        worker = _DummyAsyncWorker()
        manager.register("dummy", worker, auto_restart=False)

        await manager.start_all()
        await asyncio.sleep(0.05)

        status = manager.get_status()
        assert status["workers"]["dummy"]["running"] is True
        assert worker.started is True

        await manager.stop_all()
        assert worker.running is False

    asyncio.run(run_test())


def test_trading_loop_exposes_interval_for_async_worker_management():
    loop = TradingLoop(symbol="BTC/USDT", initial_cash=10000)
    loop.interval_seconds = 42

    assert loop.interval_seconds == 42
    status = loop.get_status()
    assert status["symbols"] == ["BTC/USDT"]