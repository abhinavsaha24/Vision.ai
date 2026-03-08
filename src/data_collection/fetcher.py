"""
Market data fetcher with configurable timeframes, pagination, and clean chronological output.

Supports large historical datasets via chunked retrieval and ensures
timestamp normalization and strictly sorted time index.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Supported intervals for yfinance (daily and longer for reliability)
VALID_INTERVALS = ("1d", "1wk", "1mo")
VALID_PERIODS = ("1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "max")
# Max period yfinance returns in one call; beyond this we paginate
CHUNK_DAYS = 365 * 2  # ~2 years per chunk for daily data


class DataFetcherError(Exception):
    """Raised when data fetching or validation fails."""

    pass


def _normalize_timestamp(ts: pd.Timestamp) -> pd.Timestamp:
    """Normalize to timezone-naive UTC date for consistency."""
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None) if ts.tz is None else ts.tz_convert("UTC").tz_localize(None)
    return ts.normalize()


def _ensure_chronological(df: pd.DataFrame) -> pd.DataFrame:
    """Sort by index ascending and remove duplicate indices."""
    df = df.sort_index(ascending=True)
    df = df[~df.index.duplicated(keep="first")]
    return df


def _clean_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows with missing OHLCV, ensure numeric, and validate."""
    required = ["open", "high", "low", "close", "volume"]
    for col in required:
        if col not in df.columns:
            raise DataFetcherError(f"Missing required column: {col}")
    df = df[required].copy()
    df = df.astype(float, copy=False)
    # Drop rows where any OHLCV is NaN or invalid
    df = df.dropna(how="any")
    # Sanity: high >= low, high >= open/close, low <= open/close
    bad = (df["high"] < df["low"]) | (df["high"] < df["open"]) | (df["high"] < df["close"])
    bad = bad | (df["low"] > df["open"]) | (df["low"] > df["close"])
    if bad.any():
        logger.warning("Dropping %d rows with invalid OHLC", bad.sum())
        df = df.loc[~bad]
    return df


class DataFetcher:
    """
    Fetches historical OHLCV data from Yahoo Finance with:
    - Configurable timeframes (interval)
    - Pagination for large history
    - Timestamp normalization and strictly chronological index
    """

    def __init__(self, data_dir: str | Path = "data") -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def fetch(
        self,
        symbol: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        period: str = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data for a symbol (single request, no pagination).

        Args:
            symbol: Ticker symbol (e.g. 'AAPL', 'BTC-USD').
            start: Start date 'YYYY-MM-DD'. Optional if period is set.
            end: End date 'YYYY-MM-DD'. Optional if period is set.
            period: Used when start/end not set: '1mo', '3mo', '6mo', '1y', '2y', '5y', '10y', 'max'.
            interval: Bar interval '1d', '1wk', or '1mo'.

        Returns:
            DataFrame with columns open, high, low, close, volume; index is datetime, sorted ascending.
        """
        if interval not in VALID_INTERVALS:
            raise DataFetcherError(f"interval must be one of {VALID_INTERVALS}")
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start, end=end, period=period, interval=interval, auto_adjust=True)

        if df is None or df.empty:
            raise DataFetcherError(f"No data retrieved for {symbol}")

        df = df.rename(columns={c: c.lower() for c in df.columns})
        df = df[["open", "high", "low", "close", "volume"]].copy()
        df = _clean_ohlcv(df)
        df.index = pd.DatetimeIndex([_normalize_timestamp(ts) for ts in df.index])
        return _ensure_chronological(df)

    def fetch_large(
        self,
        symbol: str,
        start: str,
        end: Optional[str] = None,
        interval: str = "1d",
        chunk_days: int = CHUNK_DAYS,
    ) -> pd.DataFrame:
        """
        Fetch large historical dataset with pagination (chunked by date range).

        Args:
            symbol: Ticker symbol.
            start: Start date 'YYYY-MM-DD'.
            end: End date 'YYYY-MM-DD'. If None, uses today.
            interval: '1d', '1wk', or '1mo'.
            chunk_days: Number of calendar days per request.

        Returns:
            Single DataFrame with full range, chronological and clean.
        """
        if interval not in VALID_INTERVALS:
            raise DataFetcherError(f"interval must be one of {VALID_INTERVALS}")

        end_dt = datetime.strptime(end, "%Y-%m-%d") if end else datetime.now()
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        if start_dt >= end_dt:
            raise DataFetcherError("start must be before end")

        chunks: list[pd.DataFrame] = []
        current = start_dt

        while current < end_dt:
            chunk_end = min(current + timedelta(days=chunk_days), end_dt)
            s = current.strftime("%Y-%m-%d")
            e = chunk_end.strftime("%Y-%m-%d")
            try:
                df_chunk = self.fetch(symbol, start=s, end=e, interval=interval)
                # period is ignored when start/end provided
                if df_chunk.empty:
                    current = chunk_end
                    continue
                chunks.append(df_chunk)
                # Advance past last date we got
                current = df_chunk.index.max().to_pydatetime() + timedelta(days=1)
            except DataFetcherError as err:
                logger.warning("Chunk %s to %s failed: %s", s, e, err)
                current = chunk_end

        if not chunks:
            raise DataFetcherError(f"No data retrieved for {symbol} between {start} and {end}")

        out = pd.concat(chunks, axis=0)
        out = _ensure_chronological(out)
        out = out[~out.index.duplicated(keep="first")]
        return out

    def fetch_multiple(
        self,
        symbols: list[str],
        start: Optional[str] = None,
        end: Optional[str] = None,
        period: str = "1y",
        interval: str = "1d",
    ) -> dict[str, pd.DataFrame]:
        """Fetch data for multiple symbols. Keys are symbols; values are chronological OHLCV DataFrames."""
        result: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            try:
                result[sym] = self.fetch(sym, start=start, end=end, period=period, interval=interval)
            except DataFetcherError as e:
                logger.warning("Skip %s: %s", sym, e)
        return result

    def save(
        self,
        df: pd.DataFrame,
        symbol: str,
        filename: Optional[str] = None,
    ) -> Path:
        """Save DataFrame to CSV. Index (datetime) is preserved."""
        fname = filename or f"{symbol}_{datetime.now().strftime('%Y%m%d')}.csv"
        filepath = self.data_dir / fname
        df.to_csv(filepath)
        return filepath

    def load(self, filepath: str | Path) -> pd.DataFrame:
        """Load DataFrame from CSV; index parsed as datetime. Returns chronological DataFrame."""
        df = pd.read_csv(filepath, index_col=0, parse_dates=True)
        df.index = pd.DatetimeIndex([_normalize_timestamp(ts) for ts in df.index])
        return _ensure_chronological(df)
