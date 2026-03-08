"""Prediction API routes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

router = APIRouter(prefix="/predictions", tags=["predictions"])


class PredictionRequest(BaseModel):
    """Request model for predictions."""

    symbol: str = "AAPL"
    horizon: int = 5


class PredictionResponse(BaseModel):
    """Response model for predictions."""

    symbol: str
    direction: str
    confidence: float
    horizon_days: int


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "ai-trading-system"}


@router.post("/predict", response_model=PredictionResponse)
async def get_prediction(request: PredictionRequest):
    """
    Get trading prediction for a symbol.
    Returns direction (BUY/SELL/HOLD) and confidence score.
    """
    try:
        from src.model_training.trainer import TradingModelTrainer
        from src.data_collection.fetcher import DataFetcher
        from src.feature_engineering.indicators import FeatureEngineer

        fetcher = DataFetcher()
        df = fetcher.fetch(symbol=request.symbol, period="1y")
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail=f"No data for {request.symbol}")

        engineer = FeatureEngineer()
        df = engineer.add_all_indicators(df)

        trainer = TradingModelTrainer()
        model, _ = trainer.train(df)
        direction, confidence = trainer.predict(model, df, horizon=request.horizon)

        return PredictionResponse(
            symbol=request.symbol,
            direction=direction,
            confidence=round(confidence, 4),
            horizon_days=request.horizon,
        )
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Model not ready: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
