from __future__ import annotations

import json
from typing import Any

from backend.src.platform.db import Database


def ensure_schema(db: Database) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_control (
            strategy_name TEXT PRIMARY KEY,
            enabled BOOLEAN NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            source TEXT NOT NULL,
            idempotency_key TEXT,
            payload JSONB NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS event_outbox (
            outbox_id BIGSERIAL PRIMARY KEY,
            event_id TEXT UNIQUE NOT NULL,
            stream TEXT NOT NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS signals (
            signal_id TEXT PRIMARY KEY,
            parent_event_id TEXT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity DOUBLE PRECISION NOT NULL,
            price DOUBLE PRECISION NOT NULL,
            notional DOUBLE PRECISION NOT NULL,
            confidence DOUBLE PRECISION,
            score DOUBLE PRECISION,
            payload JSONB NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS trades (
            trade_id TEXT PRIMARY KEY,
            order_id TEXT,
            parent_event_id TEXT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity DOUBLE PRECISION NOT NULL,
            price DOUBLE PRECISION,
            notional DOUBLE PRECISION,
            status TEXT NOT NULL,
            reason TEXT,
            payload JSONB NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            idempotency_key TEXT UNIQUE,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity DOUBLE PRECISION NOT NULL,
            price DOUBLE PRECISION,
            status TEXT NOT NULL,
            reason TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id BIGSERIAL PRIMARY KEY,
            cash DOUBLE PRECISION NOT NULL,
            exposure DOUBLE PRECISION NOT NULL,
            realized_pnl DOUBLE PRECISION NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio_snapshots_v2 (
            id BIGSERIAL PRIMARY KEY,
            cash DOUBLE PRECISION NOT NULL,
            exposure DOUBLE PRECISION NOT NULL,
            realized_pnl DOUBLE PRECISION NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )


def set_strategy_enabled(db: Database, strategy_name: str, enabled: bool) -> None:
    db.execute(
        """
        INSERT INTO strategy_control(strategy_name, enabled, updated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT(strategy_name)
        DO UPDATE SET enabled = EXCLUDED.enabled, updated_at = NOW()
        """,
        (strategy_name, enabled),
    )


def is_strategy_enabled(db: Database, strategy_name: str) -> bool:
    row = db.fetchone(
        "SELECT enabled FROM strategy_control WHERE strategy_name = %s",
        (strategy_name,),
    )
    if row is None:
        return False
    return bool(row[0])


def persist_event(db: Database, event: dict[str, Any]) -> None:
    db.execute(
        """
        INSERT INTO trading_events(event_id, event_type, source, idempotency_key, payload)
        VALUES (%s, %s, %s, %s, %s::jsonb)
        ON CONFLICT(event_id) DO NOTHING
        """,
        (
            event["event_id"],
            event["event_type"],
            event["source"],
            event.get("idempotency_key"),
            json.dumps(event.get("payload", {})),
        ),
    )


def get_latest_portfolio(db: Database) -> dict[str, float]:
    row = db.fetchone(
        """
        SELECT cash, exposure, realized_pnl
        FROM portfolio_snapshots_v2
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    if row is None:
        return {"cash": 100000.0, "exposure": 0.0, "realized_pnl": 0.0}
    return {"cash": float(row[0]), "exposure": float(row[1]), "realized_pnl": float(row[2])}


def insert_portfolio_snapshot(db: Database, cash: float, exposure: float, realized_pnl: float) -> None:
    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO portfolio_snapshots(cash, exposure, realized_pnl)
                VALUES (%s, %s, %s)
                """,
                (cash, exposure, realized_pnl),
            )
            cur.execute(
                """
                INSERT INTO portfolio_snapshots_v2(cash, exposure, realized_pnl)
                VALUES (%s, %s, %s)
                """,
                (cash, exposure, realized_pnl),
            )


def get_current_drawdown_pct(db: Database, lookback: int = 5000) -> float:
    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cash, exposure, realized_pnl
                FROM portfolio_snapshots_v2
                ORDER BY id DESC
                LIMIT %s
                """,
                (max(1, int(lookback)),),
            )
            rows = cur.fetchall()[::-1]

    if not rows:
        return 0.0

    peak = None
    max_drawdown = 0.0
    for cash, exposure, realized_pnl in rows:
        equity = float(cash) + float(exposure) + float(realized_pnl)
        if peak is None or equity > peak:
            peak = equity
        if peak <= 0.0:
            continue
        drawdown = max(0.0, (peak - equity) / peak)
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    return float(max_drawdown)


def insert_order(
    db: Database,
    order_id: str,
    idempotency_key: str,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    status: str,
    reason: str = "",
) -> bool:
    row = db.fetchone(
        """
        INSERT INTO orders(order_id, idempotency_key, symbol, side, quantity, price, status, reason)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (idempotency_key) DO NOTHING
        RETURNING order_id
        """,
        (order_id, idempotency_key, symbol, side, quantity, price, status, reason),
    )
    return row is not None


def insert_signal(
    db: Database,
    signal_id: str,
    parent_event_id: str,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    notional: float,
    confidence: float,
    score: float,
    payload: dict[str, Any],
) -> bool:
    row = db.fetchone(
        """
        INSERT INTO signals(
            signal_id, parent_event_id, symbol, side, quantity, price, notional,
            confidence, score, payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (signal_id) DO NOTHING
        RETURNING signal_id
        """,
        (
            signal_id,
            parent_event_id,
            symbol,
            side,
            quantity,
            price,
            notional,
            confidence,
            score,
            json.dumps(payload),
        ),
    )
    return row is not None


def insert_trade(
    db: Database,
    trade_id: str,
    order_id: str,
    parent_event_id: str,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    notional: float,
    status: str,
    reason: str,
    payload: dict[str, Any],
) -> bool:
    row = db.fetchone(
        """
        INSERT INTO trades(
            trade_id, order_id, parent_event_id, symbol, side, quantity, price,
            notional, status, reason, payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (trade_id) DO NOTHING
        RETURNING trade_id
        """,
        (
            trade_id,
            order_id,
            parent_event_id,
            symbol,
            side,
            quantity,
            price,
            notional,
            status,
            reason,
            json.dumps(payload),
        ),
    )
    return row is not None


def get_pipeline_counts(db: Database) -> dict[str, float]:
    signal_row = db.fetchone("SELECT COUNT(*) FROM signals")
    trade_row = db.fetchone("SELECT COUNT(*) FROM trades")
    order_row = db.fetchone("SELECT COUNT(*) FROM orders")
    snapshot_row = db.fetchone("SELECT COUNT(*) FROM portfolio_snapshots_v2")
    return {
        "signals": float(signal_row[0]) if signal_row else 0.0,
        "trades": float(trade_row[0]) if trade_row else 0.0,
        "orders": float(order_row[0]) if order_row else 0.0,
        "portfolio_snapshots": float(snapshot_row[0]) if snapshot_row else 0.0,
    }
