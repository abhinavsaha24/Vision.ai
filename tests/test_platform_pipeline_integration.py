from __future__ import annotations

import random

from backend.src.platform.events import EventType, TradingEvent
from backend.src.platform.live.risk_execution import ExecutionEngine
from backend.src.platform.live.types import SignalDecision
from backend.src.platform.risk_policy import RiskPolicy


def test_market_to_execution_pipeline_integration() -> None:
    # Market data stage
    market_tick = {
        "symbol": "BTCUSDT",
        "price": 60000.0,
        "volume": 12.5,
        "strategy_name": "default",
    }

    # Signal stage
    signal_event = TradingEvent(
        event_type=EventType.SIGNAL_GENERATED,
        payload={
            "symbol": market_tick["symbol"],
            "side": "buy",
            "quantity": 0.05,
            "price": market_tick["price"],
            "notional": market_tick["price"] * 0.05,
        },
        source="integration-test",
        idempotency_key="it:signal:1",
    )

    assert signal_event.event_type == EventType.SIGNAL_GENERATED

    # Risk stage
    risk_policy = RiskPolicy(
        max_position_size=1.0,
        max_notional_exposure=100000.0,
        max_drawdown_pct=0.20,
    )
    risk_result = risk_policy.evaluate(
        requested_qty=float(signal_event.payload["quantity"]),
        requested_notional=float(signal_event.payload["notional"]),
        side=str(signal_event.payload["side"]),
        current_exposure=0.0,
        current_drawdown_pct=0.0,
    )

    assert risk_result.approved is True

    # Execution stage
    execution_engine = ExecutionEngine(rng=random.Random(0))
    decision_open = SignalDecision(
        symbol="BTCUSDT",
        ts_ms=1,
        side="long",
        reason="integration_open",
        score=0.9,
        event_type="integration",
        features={},
    )
    open_report = execution_engine.execute(
        now_ms=1,
        signal=decision_open,
        quantity=float(signal_event.payload["quantity"]),
        price=float(signal_event.payload["price"]),
        spread_bps=1.5,
        visible_liquidity=100.0,
    )

    assert open_report.status in {"opened", "scaled"}

    # Portfolio stage
    portfolio = {
        "cash": 100000.0,
        "exposure": 0.0,
        "position_qty": 0.0,
        "realized_pnl": 0.0,
    }
    opened_notional = open_report.fill_price * open_report.quantity
    portfolio["cash"] -= opened_notional
    portfolio["exposure"] += opened_notional
    portfolio["position_qty"] += open_report.quantity

    # Close the position
    decision_close = SignalDecision(
        symbol="BTCUSDT",
        ts_ms=2,
        side="short",
        reason="integration_close",
        score=0.9,
        event_type="integration",
        features={},
    )
    close_report = execution_engine.execute(
        now_ms=2,
        signal=decision_close,
        quantity=float(signal_event.payload["quantity"]),
        price=float(signal_event.payload["price"] * 1.002),
        spread_bps=1.5,
        visible_liquidity=100.0,
    )

    assert close_report.status in {"closed", "partial_close"}
    portfolio["realized_pnl"] += close_report.pnl
    closed_notional = close_report.fill_price * close_report.quantity
    portfolio["cash"] += closed_notional
    portfolio["exposure"] -= closed_notional
    portfolio["position_qty"] -= close_report.quantity

    if close_report.status == "closed":
        assert abs(portfolio["position_qty"]) <= 1e-9
    else:
        assert portfolio["position_qty"] > 0.0
    assert portfolio["realized_pnl"] > 0.0
