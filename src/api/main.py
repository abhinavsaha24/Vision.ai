"""
FastAPI server for the Vision-AI trading system.
Production-ready API for AI Quant Trading Platform.
"""

from datetime import datetime
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.data_collection.fetcher import DataFetcher
from src.feature_engineering.indicators import FeatureEngineer
from src.model_training.trainer import ModelTrainer
from src.backtesting.engine import BacktestEngine
from src.prediction.predictor import Predictor
from src.api.auth_routes import router as auth_router


# --------------------------------------------------
# Logging
# --------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("vision-ai")


# --------------------------------------------------
# FastAPI App
# --------------------------------------------------

app = FastAPI(
    title="Vision-AI Trading API",
    description="AI Quant Trading Platform API",
    version="1.0.0",
)

# --------------------------------------------------
# Middleware
# --------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # change later for production frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------
# Routers
# --------------------------------------------------

app.include_router(auth_router, prefix="/auth")


# --------------------------------------------------
# Services (singletons)
# --------------------------------------------------

fetcher = DataFetcher()
engineer = FeatureEngineer()
trainer = ModelTrainer()

# Safe predictor initialization
predictor = None

try:
    predictor = Predictor()
    logger.info("Predictor loaded successfully")

except Exception as e:
    logger.error(f"Predictor failed to load: {e}")


# --------------------------------------------------
# Request Models
# --------------------------------------------------

class DataRequest(BaseModel):
    symbol: str = "BTCUSDT"
    period: str = "1y"


class TrainRequest(BaseModel):
    symbol: str = "BTCUSDT"


class PredictRequest(BaseModel):
    symbol: str = "BTCUSDT"
    horizon: int = 5


class BacktestRequest(BaseModel):
    symbol: str = "BTCUSDT"
    period: str = "1y"
    initial_capital: float = 100000.0


# --------------------------------------------------
# Health Endpoints
# --------------------------------------------------

@app.get("/")
async def root():

    return {
        "status": "ok",
        "service": "Vision-AI Trading API"
    }


@app.get("/health")
async def health():

    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat()
    }


# --------------------------------------------------
# Data Fetch
# --------------------------------------------------

@app.post("/data/fetch")
async def fetch_data(request: DataRequest):

    try:

        symbol = request.symbol.replace("USDT", "/USDT")

        df = fetcher.fetch(symbol)

        if df is None or df.empty:
            raise HTTPException(
                status_code=404,
                detail="No data found"
            )

        return {
            "symbol": request.symbol,
            "rows": len(df),
            "columns": list(df.columns)
        }

    except Exception as e:

        logger.error(f"Data fetch error: {e}")

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# --------------------------------------------------
# Feature Generation
# --------------------------------------------------

@app.post("/features/generate")
async def generate_features(request: DataRequest):

    try:

        symbol = request.symbol.replace("USDT", "/USDT")

        df = fetcher.fetch(symbol)

        df = engineer.add_all_indicators(df)

        return {
            "symbol": request.symbol,
            "rows": len(df),
            "features": list(df.columns)
        }

    except Exception as e:

        logger.error(f"Feature generation error: {e}")

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# --------------------------------------------------
# Train Model
# --------------------------------------------------

@app.post("/model/train")
async def train_model(request: TrainRequest):

    try:

        symbol = request.symbol.replace("USDT", "/USDT")

        df = fetcher.fetch(symbol)

        df = engineer.add_all_indicators(df)

        df = df.dropna()

        trainer.train(df)

        trainer.save("trading_model")

        return {
            "status": "model trained",
            "rows": len(df)
        }

    except Exception as e:

        logger.error(f"Model training error: {e}")

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# --------------------------------------------------
# Predict
# --------------------------------------------------

@app.post("/model/predict")
async def predict(request: PredictRequest):

    if predictor is None:

        raise HTTPException(
            status_code=500,
            detail="Predictor not initialized"
        )

    try:

        symbol = request.symbol.replace("USDT", "/USDT")

        preds = predictor.predict_symbol(
            symbol=symbol,
            horizon=request.horizon
        )

        return {
            "symbol": request.symbol,
            "predictions": preds
        }

    except Exception as e:

        logger.error(f"Prediction error: {e}")

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# --------------------------------------------------
# Backtest
# --------------------------------------------------

@app.post("/backtest/run")
async def run_backtest(request: BacktestRequest):

    try:

        engine = BacktestEngine(
            initial_capital=request.initial_capital
        )

        symbol = request.symbol.replace("USDT", "/USDT")

        results = engine.run_from_symbol(
            symbol=symbol,
            period=request.period
        )

        return {
            "symbol": request.symbol,
            "results": results
        }

    except Exception as e:

        logger.error(f"Backtest error: {e}")

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# --------------------------------------------------
# Run Server
# --------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=10000)    