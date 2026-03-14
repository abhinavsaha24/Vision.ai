"""
FastAPI server for the Vision-AI trading system.
Institutional-grade API for AI Quant Trading Platform.

Endpoints:
  - /health — system health
  - /health/detailed — component-level health
  - /data/fetch — fetch market data
  - /features/generate — generate features
  - /model/train — train ML models
  - /model/predict — AI prediction + quant signals
  - /model/registry — model version history
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
  - /live-trading/preflight — live trading safety checks
  - /live-trading/enable — enable live trading
  - /orders/active — active orders
  - /orders/history — order history
  - /news — aggregated multi-source news
  - /market-intelligence — trending tokens / on-chain signals
"""

from datetime import datetime
import os
import logging
import time
import threading
import uuid
from dotenv import load_dotenv

load_dotenv()

import pandas as pd

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from backend.src.data.fetcher import DataFetcher
from backend.src.features.indicators import FeatureEngineer
from backend.src.models.trainer import ModelTrainer
from backend.src.models.model_registry import ModelRegistry
from backend.src.research.backtesting_engine import BacktestEngine
from backend.src.models.predictor import Predictor

from backend.src.research.signal_engine import QuantSignalEngine
from backend.src.risk.confidence_engine import ConfidenceEngine
from backend.src.risk.risk_score import RiskScore
from backend.src.risk.risk_manager import RiskManager

from backend.src.models.regime_detector import MarketRegimeDetector
from backend.src.strategy.strategy_selector import StrategySelector
from backend.src.strategy.strategy_engine import StrategyEngine

from backend.src.sentiment.sentiment_engine import SentimentEngine
from backend.src.portfolio.portfolio_manager import PortfolioManager
from backend.src.workers.trading_loop import TradingLoop

from backend.src.exchange.exchange_adapter import PaperAdapter, BinanceAdapter
from backend.src.execution.live_safety import LiveTradingSafety
from backend.src.core.health_monitor import HealthMonitor
from backend.src.core.structured_logger import setup_logging, set_correlation_id

from backend.src.api.auth_routes import router as auth_router
from backend.src.api.admin_routes import router as admin_router
from backend.src.api.news_service import NewsAggregator
from backend.src.core.rate_limiter import RateLimiterMiddleware
from backend.src.database.db import init_db

from backend.src.core.config import settings
from backend.src.core.monitoring import MonitoringService


# --------------------------------------------------
# Logging
# --------------------------------------------------

setup_logging()
logger = logging.getLogger("vision-ai")


# --------------------------------------------------
# FastAPI App
# --------------------------------------------------

app = FastAPI(
    title="Vision-AI Trading API",
    description="Institutional-Grade AI Quant Trading Platform API",
    version="3.0.0",
)


# --------------------------------------------------
# Request ID Middleware
# --------------------------------------------------

class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
        set_correlation_id(request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

app.add_middleware(RequestIDMiddleware)
app.add_middleware(RateLimiterMiddleware, max_requests=60, window_seconds=60)

# --------------------------------------------------
# CORS Configuration
# --------------------------------------------------

origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "https://visiontrading.vercel.app",
    "https://visiontrading-a3fdz3sdy-abhinavsaha24s-projects.vercel.app",
    "https://visiontrading-oof0047z4-abhinavsaha24s-projects.vercel.app",  # current deployment
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

# --------------------------------------------------
# Global Exception Handler
# --------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled server error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc), "fallback": True}
    )

# --------------------------------------------------
# Handle browser preflight requests
# --------------------------------------------------

@app.options("/{rest_of_path:path}")
async def options_handler(rest_of_path: str):
    return JSONResponse({"status": "ok"})
# --------------------------------------------------
# Routers
# --------------------------------------------------

app.include_router(auth_router, prefix="/auth")
app.include_router(admin_router, prefix="/admin")

# --------------------------------------------------
# Database Init
# --------------------------------------------------

try:
    init_db()
    logger.info("Database initialized")
except Exception as e:
    logger.warning(f"Database init warning: {e}")

# --------------------------------------------------
# Services (Singletons)
# --------------------------------------------------

fetcher = DataFetcher()
engineer = FeatureEngineer()
trainer = ModelTrainer()
model_registry = ModelRegistry()

signal_engine = QuantSignalEngine()
confidence_engine = ConfidenceEngine()
risk_score_engine = RiskScore()
risk_manager = RiskManager()

regime_detector = MarketRegimeDetector()
strategy_selector = StrategySelector()
strategy_engine = StrategyEngine()

# Lazy-init sentiment engine (FinBERT is heavy — defer to first call)
sentiment_engine = None
def _get_sentiment_engine():
    global sentiment_engine
    if sentiment_engine is None:
        try:
            sentiment_engine = SentimentEngine()
        except Exception as e:
            logger.warning(f"SentimentEngine init failed: {e}")
            return None
    return sentiment_engine

portfolio_manager = PortfolioManager(initial_cash=100000)
news_aggregator = NewsAggregator()
health_monitor = HealthMonitor()
monitoring = MonitoringService()

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

    try:
        df = fetcher.fetch(symbol)
        if df is None or df.empty:
            return cached_df if cached_df is not None else pd.DataFrame()

        df = engineer.add_all_indicators(df)
        df = df.dropna()

        cached_df = df
        last_update = time.time()
        return df
    except Exception as e:
        logger.error(f"Market data fetch error: {e}")
        return cached_df if cached_df is not None else pd.DataFrame()


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
        "version": "3.0",
        "mode": settings.trading_mode,
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "predictor": predictor is not None,
        "paper_trading": paper_trader is not None and paper_trader.running,
        "mode": settings.trading_mode,
    }


@app.get("/health/detailed")
async def health_detailed():
    return health_monitor.check_all(
        predictor=predictor,
        paper_trader=paper_trader,
        risk_manager=risk_manager,
        cached_df=cached_df,
        last_data_update=last_update,
    )


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
    try:
        symbol = request.symbol.replace("USDT", "/USDT")

        # Market Data
        df = get_market_data(symbol)
        
        if df is None or df.empty:
            return {"error": "market data unavailable"}

        # ML Predictions (Predictor handles missing models safely now)
        preds = predictor.predict_symbol(symbol=symbol, horizon=request.horizon) if predictor else []
        if not preds:
            preds = [{"step": 1, "direction": "HOLD", "probability": 0.5, "confidence": 0.5, "regime": "unknown"}]
        
        probability = preds[0]["probability"]

        # Regime Detection
        regime = regime_detector.get_regime(df)
        strategy = strategy_selector.select_strategy(regime)

        # Strategy Signal
        strategy_result = strategy_engine.generate_detailed_signal(
            df, preds[0] if preds else {"probability": 0.5}, regime
        )

        # Sentiment (lazy-loaded)
        _se = _get_sentiment_engine()
        sentiment = _se.get_sentiment() if _se else {"score": 0.0, "label": "neutral"}
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
        logger.error(f"Prediction error: {e}", exc_info=True)
        return {
            "symbol": getattr(request, "symbol", "UNKNOWN"),
            "signal": "HOLD",
            "confidence": 0.5,
            "position_size": 0,
            "message": "fallback prediction"
        }


async def _run_prediction(symbol: str, horizon: int):
    """Shared prediction logic used by both GET and POST endpoints."""
    try:
        clean_symbol = symbol.replace("USDT", "/USDT")
        logger.info("Prediction requested for %s (horizon=%d)", symbol, horizon)

        df = get_market_data(clean_symbol)
        if df is None or df.empty:
            return {"symbol": symbol, "signal": "HOLD", "confidence": 0.5, "position_size": 0, "message": "market data unavailable"}

        preds = predictor.predict_symbol(symbol=clean_symbol, horizon=horizon) if predictor else []
        if not preds:
            preds = [{"step": 1, "direction": "HOLD", "probability": 0.5, "confidence": 0.5, "regime": "unknown"}]

        probability = preds[0]["probability"]
        regime = regime_detector.get_regime(df)
        strategy = strategy_selector.select_strategy(regime)
        strategy_result = strategy_engine.generate_detailed_signal(df, preds[0] if preds else {"probability": 0.5}, regime)

        _se = _get_sentiment_engine()
        sentiment = _se.get_sentiment() if _se else {"score": 0.0, "label": "neutral"}
        sentiment_score = sentiment.get("score", 0)

        signal_data = signal_engine.generate_signal(
            df, preds[0] if preds else {"probability": 0.5},
            sentiment_score=sentiment_score, regime=regime, strategy_result=strategy_result,
        )
        confidence = confidence_engine.calculate_confidence(
            probability=probability, regime=regime,
            volatility_regime=regime.get("volatility", "low_volatility"),
        )
        risk = risk_score_engine.calculate_risk(df)

        base_position = 0.1
        position_size = base_position * confidence
        if isinstance(risk, dict) and risk.get("risk_level") == "high":
            position_size *= 0.5
        position_size = round(position_size, 3)

        return {
            "symbol": symbol,
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
            "sentiment": {"score": sentiment_score, "label": sentiment.get("label", "neutral")},
        }
    except Exception as e:
        logger.error(f"Prediction error: {e}", exc_info=True)
        return {
            "symbol": symbol,
            "signal": "HOLD",
            "confidence": 0.5,
            "position_size": 0,
            "message": "fallback prediction"
        }


@app.get("/model/predict")
async def predict_get(symbol: str = "BTCUSDT", horizon: int = 5):
    """GET variant of predict — accepts query params for browser/fetch compatibility."""
    logger.info("GET /model/predict called for %s", symbol)
    return await _run_prediction(symbol, horizon)


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
    try:
        return portfolio_manager.get_performance()
    except Exception as e:
        logger.error(f"Portfolio performance error: {e}", exc_info=True)
        return {
            "total_return": 0,
            "win_rate": 0,
            "max_drawdown": 0,
            "total_trades": 0
        }


# ==================================================
# REGIME
# ==================================================

@app.get("/regime/current")
async def get_regime(symbol: str = "BTC/USDT"):
    try:
        df = get_market_data(symbol)
        return regime_detector.get_regime(df)
    except Exception as e:
        logger.error(f"Regime detection error: {e}", exc_info=True)
        return {"label": "unknown", "trend": "default", "volatility": "unknown"}


# ==================================================
# SENTIMENT
# ==================================================

@app.get("/sentiment/current")
async def get_sentiment():
    try:
        _se = _get_sentiment_engine()
        if _se:
            return _se.get_sentiment()
        return {"score": 0.0, "label": "neutral", "message": "Sentiment engine loading"}
    except Exception as e:
        logger.error(f"Sentiment analysis error: {e}", exc_info=True)
        return {"score": 0.0, "label": "neutral"}


# ==================================================
# RISK
# ==================================================

@app.get("/risk/status")
async def risk_status(symbol: str = "BTC/USDT"):
    try:
        df = get_market_data(symbol)
        risk = risk_score_engine.calculate_risk(df)
        risk["kill_switch"] = risk_manager.kill_switch_active if risk_manager else False
        risk["events"] = risk_manager.get_events(limit=10) if risk_manager else []
        return risk
    except Exception as e:
        logger.error(f"Risk status error: {e}", exc_info=True)
        return {
            "risk_level": "low",
            "risk_score": 0.2,
            "kill_switch": False,
            "events": []
        }


# ==================================================
# STRATEGIES
# ==================================================

@app.get("/strategies/list")
async def list_strategies():
    # Dynamically build from strategy engine registry
    strategy_list = []
    for name, instance in strategy_engine.strategies.items():
        strategy_list.append({
            "name": name.replace("_", " ").title(),
            "key": name,
            "active": instance is not None,
            "weight": strategy_engine._get_default_weight(name) if hasattr(strategy_engine, '_get_default_weight') else 0,
        })
    return {"strategies": strategy_list, "total": len(strategy_list)}


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
    try:
        if paper_trader is None:
            return {"status": "not_initialized"}
        return paper_trader.get_status()
    except Exception as e:
        logger.error(f"Paper trading status error: {e}", exc_info=True)
        return {"status": "error", "message": "Status unavailable"}


# ==================================================
# LIVE TRADING
# ==================================================

@app.get("/live-trading/preflight")
async def live_trading_preflight():
    """Run pre-flight safety checks for live trading."""
    safety = LiveTradingSafety(
        settings=settings,
        risk_manager=risk_manager,
    )
    return safety.get_report_dict()


@app.post("/live-trading/enable")
async def enable_live_trading():
    """Enable live trading (requires all pre-flight checks to pass)."""
    safety = LiveTradingSafety(
        settings=settings,
        risk_manager=risk_manager,
    )
    report = safety.run_preflight()

    if not report.all_passed:
        raise HTTPException(
            403,
            f"Pre-flight checks failed: {report.blocked_reasons}"
        )

    return {
        "status": "live_trading_ready",
        "message": "All pre-flight checks passed. Live adapter must be initialized.",
        "checks_passed": len(report.checks),
    }


# ==================================================
# ORDER TRACKING
# ==================================================

@app.get("/orders/active")
async def active_orders():
    if paper_trader is None:
        return {"orders": [], "message": "No trading loop active"}
    return {"orders": paper_trader.execution.get_active_orders()}


@app.get("/orders/history")
async def order_history(limit: int = 50):
    if paper_trader is None:
        return {"orders": [], "message": "No trading loop active"}
    return {
        "orders": paper_trader.execution.get_order_history(limit),
        "statistics": paper_trader.execution.get_order_statistics(),
    }


# ==================================================
# MODEL REGISTRY
# ==================================================

@app.get("/model/registry")
async def get_model_registry():
    return {
        "active_version": model_registry.active_version,
        "versions": model_registry.get_all_versions(),
        "performance_history": model_registry.get_performance_history(),
    }


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
# MONITORING
# ==================================================

@app.get("/monitoring/metrics")
async def get_monitoring_metrics():
    """System metrics: latency, error rates, strategy performance, risk alerts."""
    try:
        return monitoring.get_metrics()
    except Exception as e:
        logger.error(f"Monitoring metrics error: {e}")
        return {"status": "error", "message": str(e)}


# ==================================================
# Run Server
# ==================================================

if __name__ == "__main__":
    import uvicorn
    import os
    
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("backend.src.api.main:app", host="0.0.0.0", port=port, reload=False)
