import logging
import os
from pathlib import Path
from typing import Optional

from psycopg2 import pool

logger = logging.getLogger("vision-ai")


# --------------------------------------------------
# Database location
# --------------------------------------------------

DB_DIR = Path("data")
DB_DIR.mkdir(exist_ok=True)

DB_PATH = DB_DIR / "vision_ai.db"


def is_postgres_connection(conn) -> bool:
    """Return True when a DB-API connection is backed by psycopg2."""
    return conn.__class__.__module__.startswith("psycopg2")


# --------------------------------------------------
# Database connection pool manager
# --------------------------------------------------


class ConnectionPoolManager:
    """Singleton manager for the PostgreSQL connection pool."""

    _instance: Optional["ConnectionPoolManager"] = None
    _pool: Optional[pool.ThreadedConnectionPool] = None

    @classmethod
    def get_instance(cls) -> "ConnectionPoolManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def initialize(self) -> None:
        """Initialize the pool if not already created."""
        if self._pool is not None:
            return

        try:
            from backend.src.database.connection_utils import \
                get_database_connection_params
            params = get_database_connection_params()

            self._pool = pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=20,
                host=params["host"],
                port=params["port"],
                database=params["database"],
                user=params["user"],
                password=params["password"],
                connect_timeout=5,
            )
            logger.info("Database connection pool initialized [OK]")
        except Exception as e:
            logger.error("Failed to initialize database connection pool: %s", e)
            # We don't raise here — fallback to raw connections will happen in get_conn
            pass

    def get_conn(self):
        """Get a connection from the pool, or create a raw one if pool fails."""
        if self._pool is None:
            self.initialize()

        if self._pool:
            try:
                return self._pool.getconn()
            except Exception as e:
                logger.warning("Pool exhausted or failed: %s. Falling back to raw connection.", e)

        # Fallback to a single raw connection if pool isn't available
        from backend.src.database.connection_utils import \
            get_database_connection_params
        params = get_database_connection_params()
        import psycopg2
        return psycopg2.connect(
            host=params["host"],
            port=params["port"],
            database=params["database"],
            user=params["user"],
            password=params["password"],
            connect_timeout=5,
        )

    def put_conn(self, conn) -> None:
        """Return a connection to the pool."""
        if self._pool and hasattr(conn, "__class__") and "psycopg2" in conn.__class__.__module__:
            try:
                # Only put back if it came from the pool
                self._pool.putconn(conn)
            except Exception as e:
                logger.warning("Failed to return connection to pool: %s", e)
                try:
                    conn.close()
                except:
                    pass
        else:
            # If not a pool connection, just close it
            try:
                conn.close()
            except:
                pass

    def close_all(self) -> None:
        """Close all connections in the pool."""
        if self._pool:
            self._pool.closeall()
            self._pool = None
            logger.info("Database connection pool closed")


def get_connection():
    """
    Returns a database connection from the pool.
    """
    return ConnectionPoolManager.get_instance().get_conn()


def release_connection(conn):
    """
    Returns a connection to the pool. Use this instead of conn.close()
    for connections obtained via get_connection().
    """
    ConnectionPoolManager.get_instance().put_conn(conn)


# --------------------------------------------------
# Initialize database
# --------------------------------------------------


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Check if Postgres
    is_postgres = is_postgres_connection(conn)

    auto_inc = (
        "SERIAL PRIMARY KEY" if is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    )
    timestamp_type = (
        "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        if is_postgres
        else "DATETIME DEFAULT CURRENT_TIMESTAMP"
    )

    statements = [
        # Users table
        f"""
        CREATE TABLE IF NOT EXISTS users (
            id {auto_inc},
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at {timestamp_type}
        )
        """,
        # API Keys
        f"""
        CREATE TABLE IF NOT EXISTS api_keys (
            id {auto_inc},
            user_id INTEGER,
            exchange TEXT,
            api_key TEXT,
            api_secret TEXT,
            created_at {timestamp_type}
        )
        """,
        # Trades
        f"""
        CREATE TABLE IF NOT EXISTS trades (
            id {auto_inc},
            user_id INTEGER,
            symbol TEXT,
            side TEXT,
            quantity REAL,
            price REAL,
            pnl REAL DEFAULT 0,
            fees REAL DEFAULT 0,
            signal_id INTEGER,
            timestamp {timestamp_type}
        )
        """,
        # Signals
        f"""
        CREATE TABLE IF NOT EXISTS signals (
            id {auto_inc},
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            confidence REAL DEFAULT 0.5,
            probability REAL DEFAULT 0.5,
            regime TEXT,
            strategy TEXT,
            position_size REAL DEFAULT 0,
            created_at {timestamp_type}
        )
        """,
        # Portfolio Snapshots
        f"""
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id {auto_inc},
            cash REAL NOT NULL,
            equity REAL NOT NULL,
            unrealized_pnl REAL DEFAULT 0,
            realized_pnl REAL DEFAULT 0,
            open_trades INTEGER DEFAULT 0,
            total_trades INTEGER DEFAULT 0,
            win_rate REAL DEFAULT 0,
            max_drawdown REAL DEFAULT 0,
            created_at {timestamp_type}
        )
        """,
        # Equity History
        f"""
        CREATE TABLE IF NOT EXISTS equity_history (
            id {auto_inc},
            equity REAL NOT NULL,
            cash REAL NOT NULL,
            positions_value REAL DEFAULT 0,
            created_at {timestamp_type}
        )
        """,
        # Metrics
        f"""
        CREATE TABLE IF NOT EXISTS metrics (
            id {auto_inc},
            symbol TEXT,
            metric_type TEXT,
            metric_value REAL,
            created_at {timestamp_type}
        )
        """,
        # Indexes
        "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
        "CREATE INDEX IF NOT EXISTS idx_trades_user ON trades(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol)",
        "CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_equity_created ON equity_history(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_portfolio_created ON portfolio_snapshots(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_metrics_symbol ON metrics(symbol)",
    ]

    for statement in statements:
        try:
            cursor.execute(statement)
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.warning("Statement execution warning: %s", e)

    conn.close()
