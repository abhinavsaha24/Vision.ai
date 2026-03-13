"""Data API routes."""

from fastapi import APIRouter, HTTPException, Query
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

router = APIRouter(prefix="/data", tags=["data"])


@router.get("/ohlcv")
async def get_ohlcv(
    symbol: str = Query("BTCUSDT", description="Crypto symbol"),
):
    """Fetch OHLCV data for a symbol."""
    try:
        from backend.src.data.fetcher import DataFetcher

        fetcher = DataFetcher()

        # FIX: removed unsupported "period" argument
        df = fetcher.fetch(symbol=symbol)

        if df is None or df.empty:
            raise HTTPException(status_code=404, detail=f"No data for {symbol}")

        return {
            "symbol": symbol,
            "data": df.reset_index().to_dict(orient="records"),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/symbols")
async def list_symbols():
    """List available crypto symbols."""
    return {
        "symbols": [
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
            "BNBUSDT",
            "XRPUSDT"
        ],
        "description": "Supported crypto trading pairs",
    }