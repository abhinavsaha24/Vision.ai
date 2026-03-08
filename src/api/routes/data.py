"""Data API routes."""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

router = APIRouter(prefix="/data", tags=["data"])


@router.get("/ohlcv")
async def get_ohlcv(
    symbol: str = Query("AAPL", description="Stock symbol"),
    period: str = Query("1mo", description="Data period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y"),
):
    """Fetch OHLCV data for a symbol."""
    try:
        from src.data_collection.fetcher import DataFetcher

        fetcher = DataFetcher()
        df = fetcher.fetch(symbol=symbol, period=period)
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail=f"No data for {symbol}")

        return {
            "symbol": symbol,
            "period": period,
            "data": df.reset_index().to_dict(orient="records"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/symbols")
async def list_symbols():
    """List available symbols for trading."""
    return {
        "symbols": ["AAPL", "GOOGL", "MSFT", "AMZN", "META", "NVDA", "TSLA", "SPY"],
        "description": "Default symbols - extend in config for more",
    }
