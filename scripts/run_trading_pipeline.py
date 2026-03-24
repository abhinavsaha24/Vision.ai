from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus
from uuid import uuid4

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.src.platform.db import Database
from backend.src.platform.repository import (
    ensure_schema,
    get_current_drawdown_pct,
    get_latest_portfolio,
    insert_order,
    insert_signal,
    insert_trade,
)
from backend.src.platform.risk_policy import RiskPolicy


logger = logging.getLogger("trading_pipeline")


@dataclass(slots=True)
class GeneratedSignal:
    signal_id: str
    parent_event_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    notional: float
    confidence: float
    score: float
    payload: dict[str, Any]


@dataclass(slots=True)
class ApprovedDecision:
    signal: GeneratedSignal
    approved: bool
    reason: str


def _resolve_database_url(cli_database_url: str) -> str:
    if cli_database_url.strip():
        return cli_database_url.strip()

    env_database_url = os.getenv("DATABASE_URL", "").strip()
    if env_database_url:
        return env_database_url

    db_host = os.getenv("DB_HOST", "localhost").strip()
    db_port = os.getenv("DB_PORT", "5432").strip()
    db_name = os.getenv("DB_NAME", "vision_core").strip()
    db_user = os.getenv("DB_USER", "vision").strip()
    db_password = os.getenv("DB_PASSWORD", "").strip()

    if not db_password:
        raise ValueError("missing DB_PASSWORD and DATABASE_URL; provide --database-url or set DB_PASSWORD")

    return f"postgresql://{quote_plus(db_user)}:{quote_plus(db_password)}@{db_host}:{db_port}/{db_name}"


def _list_parquet_files(base_dir: Path, dataset: str) -> list[Path]:
    target = base_dir / dataset
    if not target.exists():
        return []
    return sorted(target.rglob("*.parquet"))


def _read_dataset(base_dir: Path, dataset: str) -> pd.DataFrame:
    files = _list_parquet_files(base_dir, dataset)
    if not files:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for file in files:
        try:
            frame = pd.read_parquet(file)
        except Exception as exc:
            logger.warning("skip_parquet_read_failed file=%s err=%s", file, exc)
            continue
        if frame.empty:
            continue
        frame["_source_file"] = str(file)
        frames.append(frame)

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, axis=0, ignore_index=True)
    return out


def _extract_symbol_from_path(source_file: str) -> str:
    marker = "symbol="
    for part in Path(source_file).parts:
        if part.startswith(marker):
            return part[len(marker) :]
    return "BTCUSDT"


def _normalize_trade_frame(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades

    out = trades.copy()
    if "symbol" not in out.columns:
        if "_source_file" in out.columns:
            out["symbol"] = out["_source_file"].astype(str).map(_extract_symbol_from_path)
        else:
            out["symbol"] = "BTCUSDT"

    if "ts" in out.columns:
        out["event_ts"] = pd.to_datetime(out["ts"], utc=True, errors="coerce")
    elif "exchange_ts_ms" in out.columns:
        out["event_ts"] = pd.to_datetime(pd.to_numeric(out["exchange_ts_ms"], errors="coerce"), unit="ms", utc=True, errors="coerce")
    else:
        out["event_ts"] = pd.NaT

    out["price"] = pd.to_numeric(out.get("price", 0.0), errors="coerce")
    out = out.dropna(subset=["event_ts", "price"]).sort_values(["symbol", "event_ts"]).reset_index(drop=True)
    return out


def _load_microstructure_data(micro_root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    trades = _normalize_trade_frame(_read_dataset(micro_root, "trades"))
    orderbook = _read_dataset(micro_root, "orderbook")
    logger.info(
        "DATA LOADED root=%s trade_rows=%s orderbook_rows=%s",
        micro_root,
        len(trades),
        len(orderbook),
    )
    return trades, orderbook


def _generate_signals(trades: pd.DataFrame, signal_notional: float, max_signals: int) -> list[GeneratedSignal]:
    signals: list[GeneratedSignal] = []
    if trades.empty:
        return signals

    for symbol, group in trades.groupby("symbol", sort=False):
        local = group.copy().sort_values("event_ts")
        local["prev_price"] = local["price"].shift(1)
        local = local.dropna(subset=["prev_price"])
        if local.empty:
            continue

        for _, row in local.iterrows():
            current_price = float(row["price"])
            previous_price = float(row["prev_price"])
            if current_price <= 0.0:
                continue
            if current_price > previous_price:
                side = "buy"
            elif current_price < previous_price:
                side = "sell"
            else:
                continue

            quantity = float(signal_notional / current_price)
            signal = GeneratedSignal(
                signal_id=str(uuid4()),
                parent_event_id=str(uuid4()),
                symbol=str(symbol),
                side=side,
                quantity=quantity,
                price=current_price,
                notional=float(signal_notional),
                confidence=0.60,
                score=0.55,
                payload={
                    "strategy": "simple_price_momentum",
                    "prev_price": previous_price,
                    "current_price": current_price,
                    "rule": "price_up_buy_price_down_sell",
                },
            )
            signals.append(signal)
            logger.info(
                "SIGNAL GENERATED symbol=%s side=%s price=%s qty=%s",
                signal.symbol,
                signal.side,
                signal.price,
                signal.quantity,
            )
            if len(signals) >= max_signals:
                return signals

    return signals


def _apply_risk_policy(db: Database, signals: list[GeneratedSignal], risk: RiskPolicy) -> list[ApprovedDecision]:
    decisions: list[ApprovedDecision] = []
    for signal in signals:
        latest = get_latest_portfolio(db)
        current_exposure = float(latest.get("exposure", 0.0) or 0.0)
        current_drawdown = float(get_current_drawdown_pct(db))

        check = risk.evaluate(
            requested_qty=float(signal.quantity),
            requested_notional=float(signal.notional),
            side=str(signal.side),
            current_exposure=current_exposure,
            current_drawdown_pct=current_drawdown,
        )
        decisions.append(ApprovedDecision(signal=signal, approved=bool(check.approved), reason=str(check.reason)))
        if check.approved:
            logger.info("RISK APPROVED signal_id=%s symbol=%s side=%s", signal.signal_id, signal.symbol, signal.side)
        else:
            logger.info("RISK REJECTED signal_id=%s reason=%s", signal.signal_id, check.reason)

    return decisions


def _persist_signals(db: Database, signals: list[GeneratedSignal]) -> int:
    inserted = 0
    for signal in signals:
        ok = insert_signal(
            db=db,
            signal_id=signal.signal_id,
            parent_event_id=signal.parent_event_id,
            symbol=signal.symbol,
            side=signal.side,
            quantity=float(signal.quantity),
            price=float(signal.price),
            notional=float(signal.notional),
            confidence=float(signal.confidence),
            score=float(signal.score),
            payload=signal.payload,
        )
        if ok:
            inserted += 1
    return inserted


def _execute_approved_trades(db: Database, decisions: list[ApprovedDecision]) -> int:
    executed = 0
    for decision in decisions:
        if not decision.approved:
            continue

        signal = decision.signal
        order_id = str(uuid4())
        idempotency_key = f"pipeline-order:{signal.signal_id}"
        order_inserted = insert_order(
            db=db,
            order_id=order_id,
            idempotency_key=idempotency_key,
            symbol=signal.symbol,
            side=signal.side,
            quantity=float(signal.quantity),
            price=float(signal.price),
            status="filled",
            reason="pipeline_execution",
        )
        if not order_inserted:
            continue

        trade_id = str(uuid4())
        trade_inserted = insert_trade(
            db=db,
            trade_id=trade_id,
            order_id=order_id,
            parent_event_id=signal.signal_id,
            symbol=signal.symbol,
            side=signal.side,
            quantity=float(signal.quantity),
            price=float(signal.price),
            notional=float(signal.notional),
            status="filled",
            reason="risk_approved",
            payload={
                "source": "run_trading_pipeline",
                "signal_id": signal.signal_id,
                "risk_reason": decision.reason,
            },
        )
        if trade_inserted:
            executed += 1
            logger.info(
                "TRADE EXECUTED trade_id=%s symbol=%s side=%s qty=%s price=%s",
                trade_id,
                signal.symbol,
                signal.side,
                signal.quantity,
                signal.price,
            )

    return executed


def _print_validation(db: Database) -> None:
    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT signal_id, symbol, side, quantity, price, created_at FROM signals ORDER BY created_at DESC LIMIT 5")
            recent_signals = cur.fetchall()
            cur.execute("SELECT trade_id, symbol, side, quantity, price, status, created_at FROM trades ORDER BY created_at DESC LIMIT 5")
            recent_trades = cur.fetchall()
            cur.execute("SELECT COUNT(*) FROM signals")
            signal_count = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM trades")
            trade_count = int(cur.fetchone()[0])

    print("signals_count=", signal_count)
    print("trades_count=", trade_count)
    print("recent_signals=")
    for row in recent_signals:
        print(row)
    print("recent_trades=")
    for row in recent_trades:
        print(row)


def _resolve_latest_microstructure_root(base_dir: Path, explicit: str) -> Path:
    if explicit:
        root = Path(explicit)
        if not root.is_absolute():
            root = (base_dir / root).resolve()
        return root

    matches = [p for p in base_dir.glob("microstructure_soak_*") if p.is_dir()]
    if not matches:
        raise FileNotFoundError("no microstructure_soak_* directory found under data/")
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run full trading pipeline from parquet microstructure into DB")
    parser.add_argument("--microstructure-root", default="", help="Path to microstructure_soak directory (default: latest data/microstructure_soak_*)")
    parser.add_argument("--database-url", default="", help="Postgres URL; falls back to DATABASE_URL or DB_* env")
    parser.add_argument("--signal-notional", type=float, default=25.0)
    parser.add_argument("--max-signals", type=int, default=200)
    parser.add_argument("--max-position-size", type=float, default=1.0)
    parser.add_argument("--max-notional-exposure", type=float, default=50000.0)
    parser.add_argument("--max-drawdown-pct", type=float, default=0.15)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    data_dir = ROOT / "data"
    micro_root = _resolve_latest_microstructure_root(data_dir, args.microstructure_root)
    database_url = _resolve_database_url(args.database_url)

    db = Database(database_url)
    try:
        ensure_schema(db)

        trades, _orderbook = _load_microstructure_data(micro_root)
        signals = _generate_signals(trades=trades, signal_notional=float(args.signal_notional), max_signals=max(1, int(args.max_signals)))

        risk = RiskPolicy(
            max_position_size=float(args.max_position_size),
            max_notional_exposure=float(args.max_notional_exposure),
            max_drawdown_pct=float(args.max_drawdown_pct),
        )
        decisions = _apply_risk_policy(db=db, signals=signals, risk=risk)

        inserted_signals = _persist_signals(db, signals)
        executed_trades = _execute_approved_trades(db, decisions)

        logger.info(
            "PIPELINE COMPLETE loaded_trade_rows=%s generated_signals=%s inserted_signals=%s executed_trades=%s",
            len(trades),
            len(signals),
            inserted_signals,
            executed_trades,
        )

        _print_validation(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
