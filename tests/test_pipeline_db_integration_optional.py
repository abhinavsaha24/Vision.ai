from __future__ import annotations

import os
from uuid import uuid4

import pytest

from backend.src.platform.db import Database
from backend.src.platform.repository import (
    ensure_schema,
    get_pipeline_counts,
    insert_portfolio_snapshot,
    insert_signal,
    insert_trade,
)
from backend.src.platform.risk_policy import RiskPolicy


RUN_DB_INTEGRATION = os.getenv("RUN_DB_INTEGRATION", "0").strip().lower() in {"1", "true", "yes"}
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


@pytest.mark.skipif(not RUN_DB_INTEGRATION or not DATABASE_URL, reason="requires RUN_DB_INTEGRATION=1 and DATABASE_URL")
def test_pipeline_flow_persists_signal_trade_and_portfolio() -> None:
    db = Database(DATABASE_URL)
    try:
        ensure_schema(db)

        signal_id = str(uuid4())
        trade_id = str(uuid4())
        parent_event_id = str(uuid4())

        policy = RiskPolicy(max_position_size=10.0, max_notional_exposure=100000.0, max_drawdown_pct=0.50)
        decision = policy.evaluate(
            requested_qty=0.001,
            requested_notional=60.0,
            side="buy",
            current_exposure=0.0,
            current_drawdown_pct=0.0,
        )
        assert decision.approved is True

        signal_inserted = insert_signal(
            db=db,
            signal_id=signal_id,
            parent_event_id=parent_event_id,
            symbol="BTCUSDT",
            side="buy",
            quantity=0.001,
            price=60000.0,
            notional=60.0,
            confidence=0.9,
            score=0.8,
            payload={"stage": "integration_test"},
        )
        assert signal_inserted is True

        trade_inserted = insert_trade(
            db=db,
            trade_id=trade_id,
            order_id=str(uuid4()),
            parent_event_id=parent_event_id,
            symbol="BTCUSDT",
            side="buy",
            quantity=0.001,
            price=60000.0,
            notional=60.0,
            status="filled",
            reason="integration_test",
            payload={"stage": "integration_test"},
        )
        assert trade_inserted is True

        insert_portfolio_snapshot(db=db, cash=99940.0, exposure=60.0, realized_pnl=0.0)

        counts = get_pipeline_counts(db)
        assert counts["signals"] >= 1
        assert counts["trades"] >= 1
        assert counts["portfolio_snapshots"] >= 1
    finally:
        db.close()
