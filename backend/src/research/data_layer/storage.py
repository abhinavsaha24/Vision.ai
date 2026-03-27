from __future__ import annotations

import sqlite3
from numbers import Real
from pathlib import Path

import pandas as pd


class TimeSeriesStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path.as_posix())
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.execute("PRAGMA temp_store=MEMORY;")
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ts_data (
                ts TEXT NOT NULL,
                source TEXT NOT NULL,
                symbol TEXT NOT NULL,
                value REAL,
                v1 REAL,
                v2 REAL,
                v3 REAL,
                v4 REAL,
                meta TEXT,
                PRIMARY KEY (ts, source, symbol)
            );
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ts_data_source_symbol_ts ON ts_data (source, symbol, ts);"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ts_data_symbol_ts ON ts_data (symbol, ts);"
        )
        self.conn.commit()

    def upsert_frame(self, df: pd.DataFrame, source: str, symbol: str) -> int:
        if df.empty:
            return 0
        if "ts" not in df.columns:
            raise ValueError("frame must include ts column")

        payload = []
        for _, row in df.iterrows():
            payload.append(
                (
                    str(row.get("ts")),
                    source,
                    symbol,
                    _safe_float(row.get("value")),
                    _safe_float(row.get("v1")),
                    _safe_float(row.get("v2")),
                    _safe_float(row.get("v3")),
                    _safe_float(row.get("v4")),
                    str(row.get("meta")) if row.get("meta") is not None else None,
                )
            )

        self.conn.executemany(
            """
            INSERT INTO ts_data (ts, source, symbol, value, v1, v2, v3, v4, meta)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ts, source, symbol) DO UPDATE SET
                value=excluded.value,
                v1=excluded.v1,
                v2=excluded.v2,
                v3=excluded.v3,
                v4=excluded.v4,
                meta=excluded.meta;
            """,
            payload,
        )
        self.conn.commit()
        return len(payload)

    def read_source(self, source: str, symbol: str) -> pd.DataFrame:
        q = """
            SELECT ts, source, symbol, value, v1, v2, v3, v4, meta
            FROM ts_data
            WHERE source = ? AND symbol = ?
            ORDER BY ts ASC;
        """
        return pd.read_sql_query(q, self.conn, params=(source, symbol))

    def read_sources(self, sources: list[str], symbol: str) -> pd.DataFrame:
        if not sources:
            return pd.DataFrame()
        placeholders = ",".join("?" for _ in sources)
        q = f"""
            SELECT ts, source, symbol, value, v1, v2, v3, v4, meta
            FROM ts_data
            WHERE source IN ({placeholders}) AND symbol = ?
            ORDER BY ts ASC;
        """
        params = tuple([*sources, symbol])
        return pd.read_sql_query(q, self.conn, params=params)

    def close(self) -> None:
        self.conn.close()


def _safe_float(v: object) -> float | None:
    try:
        if v is None:
            return None
        if isinstance(v, Real):
            return float(v)
        if isinstance(v, str):
            return float(v)
        return None
    except (TypeError, ValueError):
        return None
