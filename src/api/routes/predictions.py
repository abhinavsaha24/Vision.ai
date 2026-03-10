"""Prediction API routes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

router = APIRouter(prefix="/model", tags=["predictions"])


# -------- REQUEST MODEL --------

class PredictionRequest(BaseModel):
    symbol: str = "BTCUSDT"
    horizon: int = 5


# -------- RESPONSE MODEL --------

class PredictionResponse(BaseModel):
    symbol: str
    direction: str
    confidence: float
    horizon_days: int


# -------- HEALTH CHECK --------

@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "ai-trading-system"}


# -------- PREDICTION ENDPOINT --------

@router.post("/predict")
async def get_prediction(request: PredictionRequest):

    try:

        from src.model_training.trainer import ModelTrainer

        trainer = ModelTrainer()

        # Load trained model
        trainer.load("trading_model")

        predictions = trainer.predict_from_symbol(
            symbol=request.symbol,
            horizon=request.horizon
        )

        if not predictions:
            raise HTTPException(
                status_code=404,
                detail="No predictions generated"
            )

        # Return first prediction for API response
        first = predictions[0]

        return {
            "symbol": request.symbol,
            "direction": first["direction"],
            "confidence": round(float(first["probability"]), 4),
            "horizon_days": request.horizon
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )