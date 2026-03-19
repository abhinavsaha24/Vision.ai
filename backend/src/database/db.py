import logging
import os
from pathlib import Path

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
# Database connection
# --------------------------------------------------


def get_connection():
    """
    Returns a PostgreSQL database connection.
    Uses DATABASE_URL environment variable with proper parsing.
    """
    database_url = (os.getenv("DATABASE_URL") or "").strip()

    if not database_url or "postgres" not in database_url.lower():
        raise RuntimeError("DATABASE_URL must be set to a PostgreSQL connection string")

    try:
        import psycopg2

        from backend.src.database.connection_utils import \
            get_database_connection_params

        # Use our fixed connection parameter parser
        params = get_database_connection_params()

        conn = psycopg2.connect(
            host=params["host"],
            port=params["port"],
            database=params["database"],
            user=params["user"],
            password=params["password"],
            connect_timeout=5,
        )
        return conn
    except ImportError as e:
        raise RuntimeError("psycopg2 is required for PostgreSQL runtime") from e
    except Exception as e:
        raise RuntimeError(f"PostgreSQL connection failed: {e}") from e


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
