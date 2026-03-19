"""
State manager: unified persistence layer for portfolio and risk state.

Provides:
  - Save/load portfolio state (positions, equity, trades)
  - Save/load risk state (kill switch, events)
  - Dual backend: Redis for fast reads, SQLite/PostgreSQL for durability
  - Automatic state recovery on startup

Usage:
    state = StateManager(cache=redis_cache)
    state.save_portfolio(portfolio_manager.to_dict())
    restored = state.load_portfolio()
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

logger = logging.getLogger("vision-ai.state")


class StateManager:
    """
    Centralized state persistence for the trading platform.

    Writes to:
      - Redis/in-memory cache (fast, volatile) — for API reads
      - SQLite/PostgreSQL (slow, durable) — for crash recovery
    """

    def __init__(self, cache=None):
        """
        Args:
            cache: RedisCache instance (or in-memory fallback).
        """
        self._cache = cache
        self._last_db_write = 0
        self._db_write_interval = 60  # seconds between DB writes

    # --------------------------------------------------
    # Portfolio State
    # --------------------------------------------------

    def save_portfolio(self, portfolio_data: Dict) -> bool:
        """Save portfolio state to cache (and periodically to DB)."""
        try:
            # Always write to cache (fast)
            if self._cache:
                self._cache.set_json("state:portfolio", portfolio_data, ttl=300)

            # Periodically write to database (durable)
            now = time.time()
            if now - self._last_db_write > self._db_write_interval:
                self._persist_portfolio_to_db(portfolio_data)
                self._last_db_write = now

            return True
        except Exception as e:
            logger.warning("Portfolio state save failed: %s", e)
            return False

    def load_portfolio(self) -> Optional[Dict]:
        """Load portfolio state, preferring cache then falling back to DB."""
        # Try cache first
        if self._cache:
            cached = self._cache.get_json("state:portfolio")
            if cached:
                logger.info("Portfolio state restored from cache")
                return cached

        # Fall back to database
        return self._load_portfolio_from_db()

    def _persist_portfolio_to_db(self, data: Dict):
        """Write portfolio snapshot to database."""
        try:
            from backend.src.database.db import get_connection

            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO portfolio_snapshots
                   (cash, equity, unrealized_pnl, realized_pnl,
                    open_trades, total_trades, win_rate, max_drawdown)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    data.get("cash", 0),
                    data.get("current_equity", data.get("cash", 0)),
                    data.get("unrealized_pnl", 0),
                    data.get("realized_pnl", 0),
                    data.get("open_trades", 0),
                    data.get("total_trades", 0),
                    data.get("win_rate", 0),
                    data.get("max_drawdown", 0),
                ),
            )
            conn.commit()
            conn.close()
            logger.debug("Portfolio state persisted to database")
        except Exception as e:
            logger.warning("Portfolio DB persist failed: %s", e)

    def _load_portfolio_from_db(self) -> Optional[Dict]:
        """Load most recent portfolio snapshot from database."""
        try:
            from backend.src.database.db import get_connection

            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM portfolio_snapshots ORDER BY created_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            conn.close()

            if row:
                logger.info("Portfolio state restored from database")
                return {
                    "cash": row[1] if isinstance(row, tuple) else row["cash"],
                    "equity": row[2] if isinstance(row, tuple) else row["equity"],
                    "unrealized_pnl": (
                        row[3] if isinstance(row, tuple) else row["unrealized_pnl"]
                    ),
                    "realized_pnl": (
                        row[4] if isinstance(row, tuple) else row["realized_pnl"]
                    ),
                    "open_trades": (
                        row[5] if isinstance(row, tuple) else row["open_trades"]
                    ),
                    "total_trades": (
                        row[6] if isinstance(row, tuple) else row["total_trades"]
                    ),
                    "win_rate": row[7] if isinstance(row, tuple) else row["win_rate"],
                    "max_drawdown": (
                        row[8] if isinstance(row, tuple) else row["max_drawdown"]
                    ),
                }
        except Exception as e:
            logger.warning("Portfolio DB load failed: %s", e)
        return None

    # --------------------------------------------------
    # Risk State
    # --------------------------------------------------

    def save_risk_state(self, risk_data: Dict) -> bool:
        """Save risk manager state (kill switch, events)."""
        try:
            if self._cache:
                self._cache.set_json("state:risk", risk_data, ttl=300)
            return True
        except Exception as e:
            logger.warning("Risk state save failed: %s", e)
            return False

    def load_risk_state(self) -> Optional[Dict]:
        """Load risk manager state."""
        if self._cache:
            return self._cache.get_json("state:risk")
        return None

    # --------------------------------------------------
    # Trade History
    # --------------------------------------------------

    def save_trade(self, trade: Dict) -> bool:
        """Persist a trade to the database."""
        try:
            from backend.src.database.db import get_connection

            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO trades (symbol, side, quantity, price, pnl, fees)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    trade.get("symbol", ""),
                    trade.get("side", ""),
                    trade.get("quantity", 0),
                    trade.get("price", 0),
                    trade.get("pnl", 0),
                    trade.get("commission", 0),
                ),
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.warning("Trade persist failed: %s", e)
            return False

    def get_trade_history(self, limit: int = 100) -> List[Dict]:
        """Load recent trade history from database."""
        try:
            from backend.src.database.db import get_connection

            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM trades ORDER BY timestamp DESC LIMIT %s", (limit,)
            )
            rows = cur.fetchall()
            conn.close()
            return [
                {
                    "id": r[0],
                    "symbol": r[2],
                    "side": r[3],
                    "quantity": r[4],
                    "price": r[5],
                    "pnl": r[6],
                    "fees": r[7],
                    "timestamp": r[-1],
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning("Trade history load failed: %s", e)
            return []

    # --------------------------------------------------
    # Signal History
    # --------------------------------------------------

    def save_signal(self, signal: Dict) -> bool:
        """Persist a signal to the database."""
        try:
            from backend.src.database.db import get_connection

            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO signals (symbol, direction, confidence, probability,
                   regime, strategy, position_size)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    signal.get("symbol", ""),
                    signal.get("direction", "HOLD"),
                    signal.get("confidence", 0.5),
                    signal.get("probability", 0.5),
                    signal.get("regime", ""),
                    signal.get("strategy", ""),
                    signal.get("position_size", 0),
                ),
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.warning("Signal persist failed: %s", e)
            return False
