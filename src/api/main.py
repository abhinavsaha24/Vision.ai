"""FastAPI server for the AI trading system."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.data_collection.fetcher import DataFetcher
from src.feature_engineering.indicators import FeatureEngineer
from src.model_training.trainer import ModelTrainer
from src.backtesting.engine import BacktestEngine

app = FastAPI(
    title="AI Trading System API",
    description="REST API for data, predictions, and backtesting",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response models
class DataRequest(BaseModel):
    symbol: str = "AAPL"
    period: str = "1y"


class PredictRequest(BaseModel):
    symbol: str = "AAPL"
    horizon: int = 5


class BacktestRequest(BaseModel):
    symbol: str = "AAPL"
    period: str = "1y"
    initial_capital: float = 100000.0


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "AI Trading System API"}


@app.get("/health")
async def health():
    """Health check for load balancers."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.post("/data/fetch")
async def fetch_data(request: DataRequest):
    """Fetch market data for a symbol."""
    try:
        fetcher = DataFetcher()
        df = fetcher.fetch(request.symbol, period=request.period)
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail="No data found for symbol")
        return {
            "symbol": request.symbol,
            "rows": len(df),
            "columns": list(df.columns),
            "date_range": [str(df.index.min()), str(df.index.max())],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/features/generate")
async def generate_features(request: DataRequest):
    """Generate features for a symbol's data."""
    try:
        fetcher = DataFetcher()
        df = fetcher.fetch(request.symbol, period=request.period)
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail="No data found")
        engineer = FeatureEngineer()
        features_df = engineer.add_all_indicators(df)
        return {
            "symbol": request.symbol,
            "rows": len(features_df),
            "feature_columns": list(features_df.columns),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/model/train")
async def train_model(request: DataRequest):
    """Train the prediction model for a symbol."""
    try:
        trainer = ModelTrainer()
        metrics = trainer.train_from_symbol(request.symbol, period=request.period)
        return {"symbol": request.symbol, "metrics": metrics}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/model/predict")
async def predict(request: PredictRequest):
    """Get price direction predictions."""
    try:
        trainer = ModelTrainer()
        predictions = trainer.predict_from_symbol(
            request.symbol, period="1y", horizon=request.horizon
        )
        return {"symbol": request.symbol, "predictions": predictions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/backtest/run")
async def run_backtest(request: BacktestRequest):
    """Run backtest for a symbol."""
    try:
        engine = BacktestEngine(initial_capital=request.initial_capital)
        results = engine.run_from_symbol(request.symbol, period=request.period)
        return {"symbol": request.symbol, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
