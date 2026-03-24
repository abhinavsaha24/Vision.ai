from __future__ import annotations

from contextlib import contextmanager
from urllib.parse import urlparse

import psycopg2
from psycopg2 import pool


def _parse_database_url(database_url: str) -> dict[str, str | int]:
    parsed = urlparse(database_url)
    user = parsed.username or ""
    password = parsed.password or ""
    dbname = (parsed.path or "/").lstrip("/")
    missing: list[str] = []
    if not user:
        missing.append("user")
    if not password:
        missing.append("password")
    if not dbname:
        missing.append("dbname")
    if missing:
        raise ValueError(f"database_url_missing_required_fields:{','.join(missing)}")
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "dbname": dbname,
        "user": user,
        "password": password,
    }


class Database:
    def __init__(self, database_url: str):
        params = _parse_database_url(database_url)
        self.pool = pool.ThreadedConnectionPool(minconn=1, maxconn=20, **params)

    @contextmanager
    def connection(self):
        conn = self.pool.getconn()
        close_conn = False
        try:
            yield conn
            try:
                conn.commit()
            except Exception:
                close_conn = True
                raise
        except Exception:
            try:
                conn.rollback()
            except Exception:
                close_conn = True
            raise
        finally:
            self.pool.putconn(conn, close=close_conn)

    def execute(self, query: str, params: tuple | None = None) -> None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)

    def fetchone(self, query: str, params: tuple | None = None):
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return cur.fetchone()

    def close(self) -> None:
        self.pool.closeall()
