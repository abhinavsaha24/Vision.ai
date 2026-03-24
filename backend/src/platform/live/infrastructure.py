from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass
from threading import Lock
from typing import Any

import numpy as np


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InfrastructureConfig:
    max_round_trip_latency_ms: float = 180.0
    max_event_to_trade_ms: float = 220.0
    max_book_shift_bps: float = 2.5
    min_event_strength: float = 0.2
    disconnect_grace_ms: int = 2500
    max_daily_loss: float = 450.0
    circuit_breaker_loss_streak: int = 5
    processing_budget_ms: float = 4.5
    enable_cpu_affinity: bool = False
    cpu_cores: tuple[int, ...] = ()
    deployment_regions: tuple[str, ...] = ("tokyo", "singapore", "frankfurt")
    active_region: str = "tokyo"


class RingBuffer:
    """Fixed-size, allocation-free numeric ring buffer."""

    def __init__(self, size: int):
        self.size = max(32, int(size))
        self._arr = np.zeros(self.size, dtype=np.float64)
        self._cursor = 0
        self._count = 0

    def append(self, value: float) -> None:
        self._arr[self._cursor] = float(value)
        self._cursor = (self._cursor + 1) % self.size
        self._count = min(self.size, self._count + 1)

    def values(self) -> np.ndarray:
        if self._count <= 0:
            return np.empty(0, dtype=np.float64)
        if self._count < self.size:
            return self._arr[: self._count]
        idx = self._cursor
        return np.concatenate((self._arr[idx:], self._arr[:idx]))

    def percentile(self, p: float) -> float:
        vals = self.values()
        if vals.size == 0:
            return 0.0
        return float(np.percentile(vals, np.clip(p, 0.0, 100.0)))

    def mean(self) -> float:
        vals = self.values()
        if vals.size == 0:
            return 0.0
        return float(np.mean(vals))


class LatencyMonitor:
    def __init__(self, threshold_ms: float, sample_size: int = 4096):
        self.threshold_ms = float(threshold_ms)
        self.rtt_ms = RingBuffer(sample_size)
        self.pipeline_ms = RingBuffer(sample_size)

    def on_rtt(self, latency_ms: float) -> None:
        self.rtt_ms.append(latency_ms)

    def on_pipeline(self, latency_ms: float) -> None:
        self.pipeline_ms.append(latency_ms)

    def above_threshold(self, latency_ms: float | None = None) -> bool:
        if latency_ms is not None:
            return float(latency_ms) > self.threshold_ms
        return self.rtt_ms.percentile(99.0) > self.threshold_ms

    def snapshot(self) -> dict[str, float]:
        return {
            "rtt_p50_ms": self.rtt_ms.percentile(50.0),
            "rtt_p95_ms": self.rtt_ms.percentile(95.0),
            "rtt_p99_ms": self.rtt_ms.percentile(99.0),
            "pipeline_p50_ms": self.pipeline_ms.percentile(50.0),
            "pipeline_p95_ms": self.pipeline_ms.percentile(95.0),
            "pipeline_p99_ms": self.pipeline_ms.percentile(99.0),
        }


class RegionLatencyTracker:
    def __init__(self, regions: tuple[str, ...], threshold_ms: float):
        region_list = tuple(r for r in regions if r)
        self.threshold_ms = float(threshold_ms)
        self._buffers: dict[str, RingBuffer] = {r: RingBuffer(2048) for r in region_list}

    def update(self, region: str, latency_ms: float) -> None:
        if region not in self._buffers:
            self._buffers[region] = RingBuffer(2048)
        self._buffers[region].append(latency_ms)

    def reject(self, region: str) -> bool:
        buf = self._buffers.get(region)
        if buf is None:
            return False
        return buf.percentile(95.0) > self.threshold_ms

    def snapshot(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for region, buf in self._buffers.items():
            out[region] = {
                "p50_ms": buf.percentile(50.0),
                "p95_ms": buf.percentile(95.0),
                "p99_ms": buf.percentile(99.0),
            }
        return out


class InMemoryPubSubBus:
    """Object-reference pub/sub bus with no serialization overhead."""

    def __init__(self):
        self._subs: dict[str, list[asyncio.Queue[Any]]] = defaultdict(list)
        self._drop_counts: dict[str, int] = defaultdict(int)
        self._pub_locks: dict[str, Lock] = {}

    def subscribe(self, topic: str, maxsize: int = 2048) -> asyncio.Queue[Any]:
        q: asyncio.Queue[Any] = asyncio.Queue(maxsize=maxsize)
        self._subs[topic].append(q)
        return q

    def unsubscribe(self, topic: str, q: asyncio.Queue[Any]) -> None:
        queues = self._subs.get(topic, [])
        if q in queues:
            queues.remove(q)
        if not queues and topic in self._subs:
            self._subs.pop(topic, None)

    def publish_nowait(self, topic: str, payload: Any) -> None:
        lock = self._pub_locks.setdefault(topic, Lock())
        with lock:
            for q in self._subs.get(topic, []):
                if q.full():
                    try:
                        q.get_nowait()
                        self._drop_counts[topic] += 1
                    except Exception:
                        pass
                try:
                    q.put_nowait(payload)
                except Exception:
                    self._drop_counts[topic] += 1
                    continue

    def drop_counts(self) -> dict[str, int]:
        return {k: int(v) for k, v in self._drop_counts.items()}


class ExecutionGate:
    def __init__(self, config: InfrastructureConfig, latency_monitor: LatencyMonitor):
        self.config = config
        self.latency_monitor = latency_monitor

    def evaluate(
        self,
        *,
        now_ms: int,
        event_ts_ms: int,
        event_strength: float,
        expected_edge_bps: float,
        observed_edge_bps: float,
    ) -> tuple[bool, str]:
        event_to_trade_ms = float(max(0, now_ms - event_ts_ms))
        if event_to_trade_ms > self.config.max_event_to_trade_ms:
            return False, "latency_too_high"

        if self.latency_monitor.above_threshold():
            return False, "latency_guard_triggered"

        if float(event_strength) < self.config.min_event_strength:
            return False, "opportunity_decayed"

        book_shift = abs(float(observed_edge_bps) - float(expected_edge_bps))
        if book_shift > self.config.max_book_shift_bps:
            return False, "book_state_changed"

        return True, "ok"


class FaultToleranceManager:
    def __init__(self, config: InfrastructureConfig):
        self.config = config
        self.kill_switch = False
        self.venue_connected = True
        self.loss_streak = 0
        self.realized_pnl = 0.0
        self._last_trade_data_ms = 0
        self._last_depth_data_ms = 0

    def on_trade_feed(self, exchange_ts_ms: int) -> None:
        self._last_trade_data_ms = max(self._last_trade_data_ms, int(exchange_ts_ms))

    def on_depth_feed(self, exchange_ts_ms: int) -> None:
        self._last_depth_data_ms = max(self._last_depth_data_ms, int(exchange_ts_ms))

    def on_execution(self, pnl: float) -> None:
        self.realized_pnl += float(pnl)
        if pnl < 0:
            self.loss_streak += 1
        else:
            self.loss_streak = 0

    def trigger_kill_switch(self) -> None:
        self.kill_switch = True

    def allow_trading(self, now_ms: int) -> tuple[bool, str]:
        if self.kill_switch:
            return False, "kill_switch"

        if self.realized_pnl < -abs(self.config.max_daily_loss):
            return False, "max_loss_guard"

        if self.loss_streak >= self.config.circuit_breaker_loss_streak:
            return False, "circuit_breaker"

        if self._last_trade_data_ms > 0 and now_ms - self._last_trade_data_ms > self.config.disconnect_grace_ms:
            self.venue_connected = False
            return False, "trade_feed_disconnect"

        if self._last_depth_data_ms > 0 and now_ms - self._last_depth_data_ms > self.config.disconnect_grace_ms:
            self.venue_connected = False
            return False, "depth_feed_disconnect"

        self.venue_connected = True
        return True, "ok"


class MetricsCollector:
    def __init__(self):
        self.signal_to_exec_ms = RingBuffer(4096)
        self.slippage_bps = RingBuffer(4096)
        self.exec_success = RingBuffer(4096)
        self.missed_opportunities = 0

    def on_execution(self, latency_ms: float, slippage_bps: float, success: bool) -> None:
        self.signal_to_exec_ms.append(latency_ms)
        self.slippage_bps.append(slippage_bps)
        self.exec_success.append(1.0 if success else 0.0)

    def on_missed_opportunity(self) -> None:
        self.missed_opportunities += 1

    def snapshot(self) -> dict[str, float]:
        return {
            "signal_to_exec_p50_ms": self.signal_to_exec_ms.percentile(50.0),
            "signal_to_exec_p95_ms": self.signal_to_exec_ms.percentile(95.0),
            "signal_to_exec_p99_ms": self.signal_to_exec_ms.percentile(99.0),
            "slippage_p50_bps": self.slippage_bps.percentile(50.0),
            "slippage_p95_bps": self.slippage_bps.percentile(95.0),
            "execution_success_rate": float(self.exec_success.mean()),
            "missed_opportunities": float(self.missed_opportunities),
        }


class CpuAffinityManager:
    """Best-effort process pinning to reduce scheduler jitter."""

    @staticmethod
    def pin_current_process(cores: tuple[int, ...]) -> bool:
        if not cores:
            return False
        core_set: set[int] = set()
        for c in cores:
            try:
                core = int(c)
            except (TypeError, ValueError):
                continue
            if core >= 0:
                core_set.add(core)
        if not core_set:
            return False

        try:
            setter = getattr(os, "sched_setaffinity", None)
            if callable(setter):
                setter(0, core_set)
                return True
        except Exception:
            pass

        try:
            import psutil  # type: ignore

            proc = psutil.Process(os.getpid())
            proc.cpu_affinity(sorted(core_set))
            return True
        except Exception:
            return False


class InfrastructureRuntime:
    def __init__(self, config: InfrastructureConfig):
        self.config = config
        if self.config.enable_cpu_affinity:
            try:
                pinned = CpuAffinityManager.pin_current_process(self.config.cpu_cores)
                if not pinned:
                    logger.warning("cpu_affinity_not_applied cores=%s", self.config.cpu_cores)
            except Exception as exc:
                logger.warning("cpu_affinity_setup_failed cores=%s err=%s", self.config.cpu_cores, exc)
        self.bus = InMemoryPubSubBus()
        self.latency_monitor = LatencyMonitor(threshold_ms=config.max_round_trip_latency_ms)
        self.region_latency = RegionLatencyTracker(config.deployment_regions, config.max_round_trip_latency_ms)
        self.execution_gate = ExecutionGate(config=config, latency_monitor=self.latency_monitor)
        self.faults = FaultToleranceManager(config=config)
        self.metrics = MetricsCollector()
        self._start_ns = time.perf_counter_ns()

    def pipeline_now_ms(self) -> int:
        elapsed_ns = time.perf_counter_ns() - self._start_ns
        return int(elapsed_ns / 1_000_000)

    @staticmethod
    def fpga_readiness_manifest() -> dict[str, list[str]]:
        return {
            "fpga_candidates": [
                "market_data_parsing",
                "orderbook_reconstruction",
                "simple_threshold_checks",
                "pre_trade_risk_limits",
            ],
            "cpu_only": [
                "complex_alpha_logic",
                "research_validation_oos_tstat_pf",
                "cross_event_contextual_reasoning",
            ],
        }
