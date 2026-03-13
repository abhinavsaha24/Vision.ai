"""
FastAPI server for the Vision-AI trading system.
Production-ready API for AI Quant Trading Platform.

Endpoints:
  - /health — system health
  - /data/fetch — fetch market data
  - /features/generate — generate features
  - /model/train — train ML models
  - /model/predict — AI prediction + quant signals
  - /backtest/run — run backtest
  - /portfolio/status — portfolio state
  - /portfolio/performance — performance metrics
  - /regime/current — market regime
  - /sentiment/current — news sentiment
  - /risk/status — risk dashboard
  - /strategies/list — available strategies
  - /research/factor-analysis — alpha research
  - /paper-trading/start — start paper trading
  - /paper-trading/status — paper trading metrics
  - /news — aggregated multi-source news
  - /market-intelligence — trending tokens / on-chain signals
"""

from datetime import datetime
import os
import logging
import time
import threading
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.data_collection.fetcher import DataFetcher
from src.feature_engineering.indicators import FeatureEngineer
from src.model_training.trainer import ModelTrainer
from src.backtesting.engine import BacktestEngine
from src.prediction.predictor import Predictor

from src.quant.signal_engine import QuantSignalEngine
from src.quant.confidence_engine import ConfidenceEngine
from src.Risk_manager.risk_score import RiskScore
from src.Risk_manager.risk_manager import RiskManager

from src.regime.regime_detector import MarketRegimeDetector
from src.strategy.strategy_selector import StrategySelector
from src.strategy.strategy_engine import StrategyEngine

from src.sentiment.sentiment_engine import SentimentEngine
from src.Portfolio.portfolio_manager import PortfolioManager
from src.Trading.trading_loop import TradingLoop

from src.api.auth_routes import router as auth_router
from src.api.news_service import NewsAggregator


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
    description="Professional AI Quant Trading Platform API",
    version="2.0.0",
)

# --------------------------------------------------
# CORS Configuration
# --------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------
# Routers
# --------------------------------------------------

app.include_router(auth_router, prefix="/auth")

# --------------------------------------------------
# Services (Singletons)
# --------------------------------------------------

fetcher = DataFetcher()
engineer = FeatureEngineer()
trainer = ModelTrainer()

signal_engine = QuantSignalEngine()
confidence_engine = ConfidenceEngine()
risk_score_engine = RiskScore()
risk_manager = RiskManager()

regime_detector = MarketRegimeDetector()
strategy_selector = StrategySelector()
strategy_engine = StrategyEngine()

sentiment_engine = SentimentEngine()
portfolio_manager = PortfolioManager(initial_cash=100000)
news_aggregator = NewsAggregator()

# Paper trading instance
paper_trader = None
paper_trading_thread = None

# Market data cache
cached_df = None
last_update = 0


def get_market_data(symbol):
    global cached_df, last_update

    if cached_df is not None and time.time() - last_update < 30:
        return cached_df

    df = fetcher.fetch(symbol)
    df = engineer.add_all_indicators(df)
    df = df.dropna()

    cached_df = df
    last_update = time.time()

    return df


# Predictor
predictor = None
try:
    predictor = Predictor()
    logger.info("Predictor loaded successfully")
except Exception as e:
    logger.warning(f"Predictor not available: {e}")


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


class PaperTradingRequest(BaseModel):
    symbol: str = "BTC/USDT"
    initial_cash: float = 10000
    interval_seconds: int = 300


# ==================================================
# HEALTH
# ==================================================

@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "Vision-AI Trading API",
        "version": "2.0",
        "deployed": "March 13 2026",
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "predictor": predictor is not None,
        "paper_trading": paper_trader is not None and paper_trader.running,
    }


# ==================================================
# DATA
# ==================================================

@app.post("/data/fetch")
async def fetch_data(request: DataRequest):
    try:
        symbol = request.symbol.replace("USDT", "/USDT")
        df = fetcher.fetch(symbol)

        if df is None or df.empty:
            raise HTTPException(404, "No data found")

        return {
            "symbol": request.symbol,
            "rows": len(df),
            "columns": list(df.columns),
        }
    except Exception as e:
        logger.error(f"Data fetch error: {e}")
        raise HTTPException(500, str(e))


# ==================================================
# FEATURES
# ==================================================

@app.post("/features/generate")
async def generate_features(request: DataRequest):
    try:
        symbol = request.symbol.replace("USDT", "/USDT")
        df = fetcher.fetch(symbol)
        df = engineer.add_all_indicators(df)

        return {
            "symbol": request.symbol,
            "rows": len(df),
            "features": list(df.columns),
            "feature_count": len(df.columns),
        }
    except Exception as e:
        logger.error(f"Feature generation error: {e}")
        raise HTTPException(500, str(e))


# ==================================================
# MODEL TRAINING
# ==================================================

@app.post("/model/train")
async def train_model(request: TrainRequest):
    try:
        symbol = request.symbol.replace("USDT", "/USDT")
        df = fetcher.fetch(symbol)
        df = engineer.add_all_indicators(df)
        df = df.dropna()

        result = trainer.train(df)
        trainer.save("trading_model")

        return {
            "status": "model trained",
            "rows": len(df),
            "metrics": trainer.metrics,
            "top_features": trainer.metrics.get("top_features", [])[:10],
        }
    except Exception as e:
        logger.error(f"Model training error: {e}")
        raise HTTPException(500, str(e))


# ==================================================
# PREDICTION + QUANT INTELLIGENCE
# ==================================================

@app.post("/model/predict")
async def predict(request: PredictRequest):
    if predictor is None:
        raise HTTPException(500, "Predictor not initialized")

    try:
        symbol = request.symbol.replace("USDT", "/USDT")

        # ML Predictions
        preds = predictor.predict_symbol(symbol=symbol, horizon=request.horizon)
        probability = preds[0]["probability"] if preds else 0.5

        # Market Data
        df = get_market_data(symbol)

        # Regime Detection
        regime = regime_detector.get_regime(df)
        strategy = strategy_selector.select_strategy(regime)

        # Strategy Signal
        strategy_result = strategy_engine.generate_detailed_signal(
            df, preds[0] if preds else {"probability": 0.5}, regime
        )

        # Sentiment
        sentiment = sentiment_engine.get_sentiment()
        sentiment_score = sentiment.get("score", 0)

        # Signal Fusion
        signal_data = signal_engine.generate_signal(
            df,
            preds[0] if preds else {"probability": 0.5},
            sentiment_score=sentiment_score,
            regime=regime,
            strategy_result=strategy_result,
        )

        # Confidence
        confidence = confidence_engine.calculate_confidence(
            probability=probability,
            regime=regime,
            volatility_regime=regime.get("volatility", "low_volatility"),
        )

        # Risk
        risk = risk_score_engine.calculate_risk(df)

        # Position Sizing
        base_position = 0.1
        position_size = base_position * confidence
        if isinstance(risk, dict) and risk.get("risk_level") == "high":
            position_size *= 0.5
        position_size = round(position_size, 3)

        return {
            "symbol": request.symbol,
            "predictions": preds,
            "signal": signal_data["direction"],
            "signal_score": signal_data["score"],
            "signal_confidence": signal_data["confidence"],
            "components": signal_data["signals"],
            "strategy": strategy_result,
            "confidence": confidence,
            "risk": risk,
            "position_size": position_size,
            "regime": regime,
            "sentiment": {
                "score": sentiment_score,
                "label": sentiment.get("label", "neutral"),
            },
        }

    except Exception as e:
        logger.error(f"Prediction error: {e}")
        raise HTTPException(500, str(e))


# ==================================================
# BACKTEST
# ==================================================

@app.post("/backtest/run")
async def run_backtest(request: BacktestRequest):
    try:
        engine = BacktestEngine(initial_capital=request.initial_capital)
        symbol = request.symbol.replace("USDT", "/USDT")
        results = engine.run_from_symbol(symbol=symbol, period=request.period)

        return {"symbol": request.symbol, "results": results}
    except Exception as e:
        logger.error(f"Backtest error: {e}")
        raise HTTPException(500, str(e))


# ==================================================
# PORTFOLIO
# ==================================================

@app.get("/portfolio/status")
async def portfolio_status():
    return portfolio_manager.get_portfolio()


@app.get("/portfolio/performance")
async def portfolio_performance():
    return portfolio_manager.get_performance()


# ==================================================
# REGIME
# ==================================================

@app.get("/regime/current")
async def get_regime(symbol: str = "BTC/USDT"):
    try:
        df = get_market_data(symbol)
        return regime_detector.get_regime(df)
    except Exception as e:
        raise HTTPException(500, str(e))


# ==================================================
# SENTIMENT
# ==================================================

@app.get("/sentiment/current")
async def get_sentiment():
    try:
        return sentiment_engine.get_sentiment()
    except Exception as e:
        raise HTTPException(500, str(e))


# ==================================================
# RISK
# ==================================================

@app.get("/risk/status")
async def risk_status(symbol: str = "BTC/USDT"):
    try:
        df = get_market_data(symbol)
        risk = risk_score_engine.calculate_risk(df)
        risk["kill_switch"] = risk_manager.kill_switch_active
        risk["events"] = risk_manager.get_events(limit=10)
        return risk
    except Exception as e:
        raise HTTPException(500, str(e))


# ==================================================
# STRATEGIES
# ==================================================

@app.get("/strategies/list")
async def list_strategies():
    return {
        "strategies": [
            {"name": "AI Prediction", "type": "ml", "weight": 0.30},
            {"name": "Momentum", "type": "trend", "weight": 0.15},
            {"name": "Mean Reversion (RSI)", "type": "reversion", "weight": 0.15},
            {"name": "Breakout", "type": "trend", "weight": 0.10},
            {"name": "MA Crossover", "type": "trend", "weight": 0.05},
            {"name": "Volatility Breakout", "type": "volatility", "weight": 0.05},
            {"name": "Volatility Compression", "type": "volatility", "weight": 0.05},
            {"name": "Volume Spike", "type": "flow", "weight": 0.05},
            {"name": "Order Book Imbalance", "type": "flow", "weight": 0.10},
        ],
    }


# ==================================================
# PAPER TRADING
# ==================================================

@app.post("/paper-trading/start")
async def start_paper_trading(request: PaperTradingRequest):
    global paper_trader, paper_trading_thread

    if paper_trader and paper_trader.running:
        return {"status": "already_running", "cycles": paper_trader.cycle_count}

    paper_trader = TradingLoop(
        symbol=request.symbol,
        initial_cash=request.initial_cash,
    )

    def run_loop():
        paper_trader.start(interval_seconds=request.interval_seconds)

    paper_trading_thread = threading.Thread(target=run_loop, daemon=True)
    paper_trading_thread.start()

    return {"status": "started", "symbol": request.symbol}


@app.post("/paper-trading/stop")
async def stop_paper_trading():
    global paper_trader
    if paper_trader:
        paper_trader.stop()
        return {"status": "stopped", "cycles": paper_trader.cycle_count}
    return {"status": "not_running"}


@app.get("/paper-trading/status")
async def paper_trading_status():
    if paper_trader is None:
        return {"status": "not_initialized"}
    return paper_trader.get_status()


# ==================================================
# NEWS AGGREGATION
# ==================================================

@app.get("/news")
async def get_news(limit: int = 30):
    """Aggregated news from CryptoPanic, Finnhub, NewsAPI, CoinGecko."""
    try:
        articles = news_aggregator.get_news(limit=limit)
        return {"articles": articles, "count": len(articles)}
    except Exception as e:
        logger.error(f"News error: {e}")
        return {"articles": [], "count": 0}


# ==================================================
# MARKET INTELLIGENCE
# ==================================================

@app.get("/market-intelligence")
async def market_intelligence():
    """CoinGecko trending coins + market overview."""
    try:
        import requests as req
        trending = req.get("https://api.coingecko.com/api/v3/search/trending", timeout=10).json()
        global_data = req.get("https://api.coingecko.com/api/v3/global", timeout=10).json()

        coins = []
        for item in trending.get("coins", [])[:10]:
            c = item.get("item", {})
            coins.append({
                "name": c.get("name"),
                "symbol": c.get("symbol"),
                "rank": c.get("market_cap_rank"),
                "thumb": c.get("thumb"),
            })

        gd = global_data.get("data", {})
        return {
            "trending_coins": coins,
            "total_market_cap_usd": gd.get("total_market_cap", {}).get("usd", 0),
            "total_volume_24h": gd.get("total_volume", {}).get("usd", 0),
            "btc_dominance": gd.get("market_cap_percentage", {}).get("btc", 0),
            "active_cryptocurrencies": gd.get("active_cryptocurrencies", 0),
        }
    except Exception as e:
        logger.error(f"Market intelligence error: {e}")
        return {"trending_coins": [], "error": str(e)}


# ==================================================
# ALPHA RESEARCH
# ==================================================

@app.get("/research/feature-importance")
async def feature_importance():
    if not trainer.metadata.feature_importances:
        raise HTTPException(404, "No trained model — train first")
    return {"importance": trainer.get_feature_importance(top_n=20)}


# ==================================================
# Run Server
# ==================================================

if __name__ == "__main__":
    import uvicorn
    # Make compatible with Render assigning dynamic $PORT
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=port, reload=False)