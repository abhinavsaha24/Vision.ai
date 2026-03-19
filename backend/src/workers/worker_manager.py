"""
Worker manager: lifecycle management for background trading workers.

Responsibilities:
  - Start/stop workers during FastAPI lifespan
  - Monitor worker health via heartbeats
  - Restart on failure with exponential backoff
  - Track worker metrics (restarts, errors, uptime)

Usage:
    manager = WorkerManager()
    manager.register("trading_loop", TradingLoop(...))
    await manager.start_all()   # called during lifespan startup
    await manager.stop_all()    # called during lifespan shutdown
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger("vision-ai.workers")


@dataclass
class WorkerInfo:
    """Metadata for a registered worker."""

    name: str
    worker: object
    task: Optional[asyncio.Task] = None
    running: bool = False
    restart_count: int = 0
    max_restarts: int = 10
    last_heartbeat: float = 0
    last_error: str = ""
    started_at: str = ""
    auto_restart: bool = True


class WorkerManager:
    """
    Manages background workers for the trading platform.

    Workers run as asyncio Tasks, isolated from the API server.
    Each worker gets its own error boundary and restart logic.
    """

    def __init__(self):
        self._workers: Dict[str, WorkerInfo] = {}
        self._shutdown_event = asyncio.Event()

    # ---- Registration ----

    def register(
        self,
        name: str,
        worker: object,
        auto_restart: bool = True,
        max_restarts: int = 10,
    ):
        """Register a worker for lifecycle management."""
        self._workers[name] = WorkerInfo(
            name=name,
            worker=worker,
            auto_restart=auto_restart,
            max_restarts=max_restarts,
        )
        logger.info("Worker '%s' registered", name)

    # ---- Start / Stop ----

    async def start_all(self):
        """Start all registered workers."""
        for name, info in self._workers.items():
            await self._start_worker(name)
        logger.info("Started %s worker(s)", len(self._workers))

    async def start_worker(self, name: str):
        """Start a specific worker."""
        if name in self._workers:
            await self._start_worker(name)

    async def _start_worker(self, name: str):
        """Internal: start a single worker with error handling."""
        info = self._workers[name]

        if info.running:
            logger.warning("Worker '%s' already running", name)
            return

        async def _run_with_restart():
            backoff = 1.0
            while not self._shutdown_event.is_set():
                try:
                    info.running = True
                    info.started_at = datetime.now(timezone.utc).isoformat()
                    info.last_heartbeat = time.time()
                    logger.info("Worker '%s' starting...", name)

                    # Run the worker's main loop
                    worker = info.worker
                    if hasattr(worker, "start_async"):
                        await worker.start_async()
                    elif hasattr(worker, "run_cycle"):
                        # Wrap sync cycle-based workers
                        await self._run_cycle_worker(name, worker)
                    else:
                        logger.error("Worker '%s' has no start_async or run_cycle method", name)
                        break

                except asyncio.CancelledError:
                    logger.info("Worker '%s' cancelled", name)
                    break
                except Exception as e:
                    info.last_error = str(e)
                    info.restart_count += 1
                    logger.error(
                        f"Worker '{name}' crashed "
                        f"({info.restart_count}/{info.max_restarts}): {e}"
                    )

                    if not info.auto_restart or info.restart_count >= info.max_restarts:
                        logger.critical("Worker '%s' exceeded max restarts - stopping", name)
                        break

                    # Exponential backoff
                    wait = min(backoff * (2 ** (info.restart_count - 1)), 60.0)
                    logger.info("Worker '%s' restarting in %.1fs ...", name, wait)
                    await asyncio.sleep(wait)
                finally:
                    info.running = False

        info.task = asyncio.create_task(_run_with_restart())

    async def _run_cycle_worker(self, name: str, worker, interval: int = 300):
        """Run a cycle-based worker as an async loop."""
        info = self._workers[name]
        worker.running = True

        while worker.running and not self._shutdown_event.is_set():
            info.last_heartbeat = time.time()

            # Run cycle in thread pool to avoid blocking event loop
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, worker.run_cycle)

            # Use asyncio.sleep so we can be cancelled
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

        worker.running = False

    async def stop_all(self):
        """Gracefully stop all workers."""
        self._shutdown_event.set()

        for name, info in self._workers.items():
            await self._stop_worker(name)

        logger.info("All workers stopped")

    async def stop_worker(self, name: str):
        """Stop a specific worker."""
        if name in self._workers:
            await self._stop_worker(name)

    async def _stop_worker(self, name: str):
        """Internal: stop a single worker."""
        info = self._workers[name]

        # Signal the worker to stop
        if hasattr(info.worker, "stop"):
            info.worker.stop()

        # Cancel the asyncio task
        if info.task and not info.task.done():
            info.task.cancel()
            try:
                await asyncio.wait_for(info.task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        info.running = False
        logger.info("Worker '%s' stopped", name)

    # ---- Health ----

    def get_status(self) -> Dict:
        """Get status of all workers."""
        workers = {}
        for name, info in self._workers.items():
            heartbeat_age = (
                time.time() - info.last_heartbeat if info.last_heartbeat else -1
            )
            workers[name] = {
                "running": info.running,
                "restart_count": info.restart_count,
                "heartbeat_age_seconds": round(heartbeat_age, 1),
                "last_error": info.last_error,
                "started_at": info.started_at,
                "healthy": info.running and heartbeat_age < 600,  # 10-min timeout
            }

        return {
            "total_workers": len(self._workers),
            "running": sum(1 for w in self._workers.values() if w.running),
            "workers": workers,
        }

    def is_healthy(self) -> bool:
        """Check if all workers are healthy."""
        for info in self._workers.values():
            if info.running:
                age = time.time() - info.last_heartbeat if info.last_heartbeat else 999
                if age > 600:
                    return False
        return True
