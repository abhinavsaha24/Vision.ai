from __future__ import annotations

import json
import random

import pytest

from backend.src.platform.api_service import _flush_outbox
from backend.src.platform.live.infrastructure import (
    ExecutionGate,
    FaultToleranceManager,
    InfrastructureConfig,
    LatencyMonitor,
)
from backend.src.platform.live.risk_execution import ExecutionEngine
from backend.src.platform.live.types import SignalDecision
from backend.src.platform.workers import execution_engine as execution_worker_module


def test_exchange_api_failure_retries_without_unsafe_success(monkeypatch) -> None:
    worker = object.__new__(execution_worker_module.ExecutionEngineWorker)
    worker.db = object()

    def _boom(*_args, **_kwargs):
        raise RuntimeError("exchange_down")

    monkeypatch.setattr(execution_worker_module.settings, "execution_retry_limit", 2)
    monkeypatch.setattr(execution_worker_module.settings, "execution_retry_delay_seconds", 0.0)
    monkeypatch.setattr(execution_worker_module, "insert_order", _boom)

    event = execution_worker_module.TradingEvent(
        event_type=execution_worker_module.EventType.SIGNAL_APPROVED,
        payload={"symbol": "BTCUSDT", "side": "buy", "quantity": 0.01, "price": 100000.0},
        source="test",
        idempotency_key="exchange-failure",
    )

    ok, reason = execution_worker_module.ExecutionEngineWorker._place_order_with_retry(worker, event)
    assert ok is False
    assert "exchange_down" in reason


def test_latency_spike_blocks_execution_gate() -> None:
    cfg = InfrastructureConfig(max_event_to_trade_ms=200.0)
    latency = LatencyMonitor(threshold_ms=300.0)
    gate = ExecutionGate(cfg, latency)

    ok, reason = gate.evaluate(
        now_ms=10_000,
        event_ts_ms=9_000,
        event_strength=0.8,
        expected_edge_bps=2.0,
        observed_edge_bps=2.1,
    )
    assert ok is False
    assert reason == "latency_too_high"


def test_websocket_disconnect_enters_safe_mode() -> None:
    cfg = InfrastructureConfig(disconnect_grace_ms=1000)
    faults = FaultToleranceManager(cfg)
    faults.on_trade_feed(1_000)
    faults.on_depth_feed(1_000)

    can_trade, reason = faults.allow_trading(now_ms=2_500)
    assert can_trade is False
    assert reason in {"trade_feed_disconnect", "depth_feed_disconnect"}


def test_partial_fill_is_handled_without_full_assumption() -> None:
    engine = ExecutionEngine(
        rng=random.Random(7),
        partial_fill_threshold=0.05,
        partial_fill_min_ratio=0.2,
    )
    signal = SignalDecision(
        symbol="BTCUSDT",
        ts_ms=1,
        side="long",
        reason="partial_fill_test",
        score=0.9,
        event_type="test",
        features={},
    )
    report = engine.execute(
        now_ms=1,
        signal=signal,
        quantity=10.0,
        price=100.0,
        spread_bps=3.0,
        visible_liquidity=20.0,
    )

    assert report.requested_quantity == 10.0
    assert report.filled_quantity <= report.requested_quantity
    if report.status == "rejected":
        assert report.filled_quantity == 0.0
    elif report.filled_quantity < report.requested_quantity:
        assert report.detail == "partial_fill"


class _OutboxCursorFailing:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, _query: str, _params=None):
        raise RuntimeError("database_down")

    def fetchall(self):
        return []


class _OutboxConnFailing:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return _OutboxCursorFailing()


class _OutboxDbFailing:
    def connection(self):
        return _OutboxConnFailing()


class _QueueSpy:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    def publish(self, stream: str, payload: dict) -> str:
        self.published.append((stream, payload))
        return "ok"


def test_database_downtime_prevents_outbox_publish() -> None:
    db = _OutboxDbFailing()
    queue = _QueueSpy()

    with pytest.raises(RuntimeError, match="database_down"):
        _flush_outbox(db, queue, max_rows=100)

    assert queue.published == []
