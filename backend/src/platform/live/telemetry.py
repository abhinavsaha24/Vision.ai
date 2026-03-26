from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from pathlib import Path

from backend.src.platform.live.types import ExecutionReport, SignalDecision

logger = logging.getLogger(__name__)


class AsyncJsonlLogger:
    def __init__(self, path: str):
        self.path = Path(path)
        self.queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=5000)
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._running = True
        self._task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            try:
                await asyncio.wait_for(self.queue.join(), timeout=2.0)
            except Exception:
                pass
            if not self._task.done():
                self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def log(self, payload: dict) -> None:
        if self.queue.full():
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except Exception:
                pass
        await self.queue.put(payload)

    def log_nowait(self, payload: dict) -> None:
        if self.queue.full():
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except Exception:
                pass
        try:
            self.queue.put_nowait(payload)
        except Exception:
            pass

    async def _worker(self) -> None:
        while self._running or not self.queue.empty():
            try:
                payload = await self.queue.get()
                line = json.dumps(payload, separators=(",", ":"), ensure_ascii=True) + "\n"
                await asyncio.to_thread(self._append_line, line)
                self.queue.task_done()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("live_logger_error err=%s", exc)

    def _append_line(self, line: str) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line)


class LiveValidationMonitor:
    """Tracks rolling live quality and disables strategy on sustained degradation."""

    def __init__(self, performance_window: int, disable_min_trades: int, disable_min_expectancy: float, disable_min_sharpe: float, disable_max_drawdown: float):
        self.performance_window = max(30, int(performance_window))
        self.disable_min_trades = max(10, int(disable_min_trades))
        self.disable_min_expectancy = float(disable_min_expectancy)
        self.disable_min_sharpe = float(disable_min_sharpe)
        self.disable_max_drawdown = float(disable_max_drawdown)
        self.realized_pnls: deque[float] = deque(maxlen=self.performance_window)
        self.equity: deque[float] = deque(maxlen=self.performance_window)
        self._equity_value = 0.0
        self.strategy_enabled = True

    def on_execution(self, report: ExecutionReport) -> dict[str, float | bool]:
        self.realized_pnls.append(float(report.pnl))
        self._equity_value += float(report.pnl)
        self.equity.append(self._equity_value)

        metrics = self.metrics()
        self.strategy_enabled = not self._degraded(metrics)
        metrics["enabled"] = self.strategy_enabled
        return metrics

    def metrics(self) -> dict[str, float | bool]:
        n = len(self.realized_pnls)
        if n == 0:
            return {
                "trades": 0.0,
                "win_rate": 0.0,
                "expectancy": 0.0,
                "sharpe": 0.0,
                "drawdown": 0.0,
                "enabled": self.strategy_enabled,
            }

        pnls = list(self.realized_pnls)
        wins = [p for p in pnls if p > 0]
        mean = sum(pnls) / max(1, n)
        variance = sum((x - mean) ** 2 for x in pnls) / max(1, n - 1)
        std = variance ** 0.5
        sharpe = (mean / std) * (n ** 0.5) if std > 1e-9 else 0.0
        peak = float("-inf")
        max_dd = 0.0
        for eq in self.equity:
            peak = max(peak, eq)
            max_dd = min(max_dd, eq - peak)

        return {
            "trades": float(n),
            "win_rate": float(len(wins) / max(1, n)),
            "expectancy": float(mean),
            "sharpe": float(sharpe),
            "drawdown": float(max_dd),
            "enabled": self.strategy_enabled,
        }

    def _degraded(self, metrics: dict[str, float | bool]) -> bool:
        trades = int(float(metrics.get("trades", 0.0) or 0.0))
        if trades < self.disable_min_trades:
            return False
        expectancy = float(metrics.get("expectancy", 0.0) or 0.0)
        sharpe = float(metrics.get("sharpe", 0.0) or 0.0)
        drawdown = float(metrics.get("drawdown", 0.0) or 0.0)
        if expectancy < self.disable_min_expectancy:
            return True
        if sharpe < self.disable_min_sharpe:
            return True
        if drawdown < -abs(self.disable_max_drawdown):
            return True
        return False


def build_log_payload(
    signal: SignalDecision,
    execution: ExecutionReport,
    validation_metrics: dict[str, float | bool],
    gate_reason: str,
    event_context: dict | None = None,
) -> dict:
    payload = {
        "timestamp_ms": execution.ts_ms,
        "symbol": signal.symbol,
        "signal": {
            "side": signal.side,
            "event_type": signal.event_type,
            "reason": signal.reason,
            "score": signal.score,
            "features": signal.features,
        },
        "decision": {
            "gate_reason": gate_reason,
            "execution_status": execution.status,
        },
        "execution": {
            "side": execution.side,
            "qty": execution.quantity,
            "requested_price": execution.requested_price,
            "fill_price": execution.fill_price,
            "slippage_bps": execution.slippage_bps,
            "fill_probability": execution.fill_probability,
            "pnl": execution.pnl,
            "detail": execution.detail,
        },
        "validation": validation_metrics,
    }
    if event_context:
        payload["event"] = event_context
    return payload
