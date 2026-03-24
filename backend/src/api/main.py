"""
FastAPI server for the Vision-AI trading system.
Institutional-grade API for AI Quant Trading Platform.

Architecture:
  - All heavy service initialization is deferred to the async lifespan()
    context manager so that uvicorn binds to $PORT instantly.
  - Services live on app.state.services (typed AppServices dataclass).
  - Endpoints access services via the _svc() helper.

Endpoints:
  - /health - system health
  - /health/detailed - component-level health
  - /data/fetch - fetch market data
  - /features/generate - generate features
  - /model/train - train ML models
  - /model/predict - AI prediction + quant signals
  - /model/registry - model version history
  - /backtest/run - run backtest
  - /portfolio/status - portfolio state
  - /portfolio/performance - performance metrics
  - /regime/current - market regime
  - /sentiment/current - news sentiment
  - /risk/status - risk dashboard
  - /strategies/list - available strategies
  - /research/factor-analysis - alpha research
  - /paper-trading/start - start paper trading
  - /paper-trading/status - paper trading metrics
  - /live-trading/preflight - live trading safety checks
  - /live-trading/enable - enable live trading
  - /orders/active - active orders
  - /orders/history - order history
  - /news - aggregated multi-source news
  - /market-intelligence - trending tokens / on-chain signals
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional
from urllib.parse import urljoin

from dotenv import load_dotenv

load_dotenv()

import pandas as pd
import requests
from fastapi import (Depends, FastAPI, HTTPException, Request, WebSocket,
                     WebSocketDisconnect)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from backend.src.api.admin_routes import router as admin_router
from backend.src.api.auth_routes import router as auth_router
from backend.src.database.db import init_db, ConnectionPoolManager, get_connection, release_connection
from backend.src.auth.auth_service import get_current_user
# Lightweight imports only — these don't trigger heavy computation
from backend.src.core.config import settings
from backend.src.core.rate_limiter import RateLimiterMiddleware
from backend.src.core.structured_logger import (set_correlation_id,
                                                setup_logging)

# --------------------------------------------------
# Logging (lightweight — safe at module level)
# --------------------------------------------------

setup_logging()
logger = logging.getLogger("vision-ai")


# --------------------------------------------------
# AppServices — typed container for all singletons
# --------------------------------------------------


@dataclass
class AppServices:
    """Holds every service singleton. Created during lifespan startup."""

    fetcher: object = None
    engineer: object = None
    trainer: object = None
    model_registry: object = None
    signal_engine: object = None
    confidence_engine: object = None
    risk_score_engine: object = None
    risk_manager: object = None
    regime_detector: object = None
    strategy_selector: object = None
    strategy_engine: object = None
    sentiment_engine: object = None
    portfolio_manager: object = None
    news_aggregator: object = None
    health_monitor: object = None
    monitoring: object = None
    cache: object = None
    predictor: object = None

    # Paper trading
    paper_trader: object = None
    paper_trading_thread: object = None
    worker_manager: object = None

    # Metrics collection
    execution_metrics_collector: object = None

    # Realtime market data and meta-alpha
    realtime_feed: object = None
    meta_alpha_engine: object = None
    drift_detector: object = None

    # Market data cache
    cached_df: object = None
    last_update: float = 0
    prediction_probability_history: dict = field(default_factory=dict)

    # Flags
    initialized: bool = False


# --------------------------------------------------
# Lifespan — ALL heavy initialization happens here
# --------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Async lifespan context manager for FastAPI.

    START: initialises all services AFTER uvicorn has bound to $PORT.
    STOP:  graceful shutdown of background workers.
    """
    svc = AppServices()
    logger.info("Starting service initialization...")

    try:
        settings.validate_security()

        # ---- Database Pool ----
        ConnectionPoolManager.get_instance().initialize()
        logger.info("Database connection pool initialized")

        # ---- Database ----
        try:
            init_db()
            logger.info("Database initialized")
        except Exception as e:
            logger.warning("Database init warning: %s", e)

        # ---- Data & Features ----
        from backend.src.data.fetcher import DataFetcher
        from backend.src.features.indicators import FeatureEngineer

        svc.fetcher = DataFetcher()
        svc.engineer = FeatureEngineer()

        # ---- Model registry (lightweight) ----
        from backend.src.models.model_registry import ModelRegistry

        svc.model_registry = ModelRegistry()

        # ---- Signal / Confidence / Risk ----
        from backend.src.research.signal_engine import QuantSignalEngine
        from backend.src.risk.confidence_engine import ConfidenceEngine
        from backend.src.risk.risk_manager import RiskManager
        from backend.src.risk.risk_score import RiskScore

        svc.signal_engine = QuantSignalEngine()
        svc.confidence_engine = ConfidenceEngine()
        svc.risk_score_engine = RiskScore()
        svc.risk_manager = RiskManager()

        # ---- Regime / Strategy ----
        from backend.src.models.regime_detector import MarketRegimeDetector
        from backend.src.strategy.strategy_engine import StrategyEngine
        from backend.src.strategy.strategy_selector import StrategySelector

        svc.regime_detector = MarketRegimeDetector()
        svc.strategy_selector = StrategySelector()
        svc.strategy_engine = StrategyEngine()

        # ---- Portfolio ----
        from backend.src.portfolio.portfolio_manager import PortfolioManager

        svc.portfolio_manager = PortfolioManager(initial_cash=100000)

        # ---- News ----
        from backend.src.api.news_service import NewsAggregator

        svc.news_aggregator = NewsAggregator()

        # ---- Health & Monitoring ----
        from backend.src.core.health_monitor import HealthMonitor
        from backend.src.core.monitoring import MonitoringService
        from backend.src.monitoring.execution_metrics_collector import \
            ExecutionMetricsCollector

        svc.health_monitor = HealthMonitor()
        svc.monitoring = MonitoringService()
        svc.execution_metrics_collector = ExecutionMetricsCollector(window_size=100)
        logger.info("Execution metrics collector initialized")

        # ---- Cache ----
        from backend.src.core.cache import RedisCache

        svc.cache = RedisCache(
            url=settings.redis_url,
            default_ttl=settings.redis_ttl,
            enabled=settings.redis_enabled,
        )

        # ---- Worker manager ----
        from backend.src.workers.worker_manager import WorkerManager

        svc.worker_manager = WorkerManager()

        # ---- Real-time market feed ----
        from backend.src.data.realtime_feed import RealtimeMarketFeed

        svc.realtime_feed = RealtimeMarketFeed(
            cache=svc.cache, stale_after_seconds=15.0
        )
        await svc.realtime_feed.start([settings.default_symbol])

        # ---- Meta alpha engine ----
        from backend.src.models.drift_detector import DriftDetector
        from backend.src.models.meta_alpha_engine import MetaAlphaEngine

        svc.meta_alpha_engine = MetaAlphaEngine()
        svc.drift_detector = DriftDetector(psi_threshold=0.22, perf_drop_threshold=0.10)

        # ---- Predictor (lazy — may fail if no model file) ----
        try:
            from backend.src.models.predictor import Predictor

            svc.predictor = Predictor()
            logger.info("Predictor loaded successfully")
        except Exception as e:
            logger.warning("Predictor not available: %s", e)

        # ---- Auto-start Paper Trading (disabled by default for stateless API) ----
        if settings.paper_trading_api_autostart:
            try:
                from backend.src.workers.trading_loop import TradingLoop

                svc.paper_trader = TradingLoop(
                    symbol=settings.default_symbol.replace("/", ""),
                    initial_cash=settings.paper_trading_initial_cash,
                    metrics_collector=svc.execution_metrics_collector,
                )
                svc.paper_trader.interval_seconds = settings.paper_trading_interval
                svc.worker_manager.register(
                    "paper_trading", svc.paper_trader,
                    auto_restart=True, max_restarts=10,
                )
                await svc.worker_manager.start_worker("paper_trading")
                logger.info(
                    "Paper trading auto-started for %s (interval=%ds)",
                    settings.default_symbol, settings.paper_trading_interval,
                )
            except Exception as e:
                logger.warning("Paper trading auto-start failed: %s", e)
        else:
            logger.info("Paper trading auto-start disabled; run trading as a separate worker service")

        svc.initialized = True
        app.state.services = svc
        logger.info("All services initialized [OK]")

    except Exception as e:
        logger.error("Service initialization error: %s", e, exc_info=True)
        # Provide a partially-initialized services object so endpoints
        # can still return health/error information.
        svc.initialized = False
        app.state.services = svc

    yield  # ---- server is running ----

    # ---- Shutdown ----
    logger.info("Shutting down services...")
    if svc.worker_manager and hasattr(svc.worker_manager, "stop_all"):
        await svc.worker_manager.stop_all()
    elif svc.paper_trader and hasattr(svc.paper_trader, "stop"):
        svc.paper_trader.stop()
    if svc.realtime_feed and hasattr(svc.realtime_feed, "stop"):
        await svc.realtime_feed.stop()
    logger.info("Shutdown complete [OK]")


# --------------------------------------------------
# FastAPI App
# --------------------------------------------------

app = FastAPI(
    title="Vision-AI Trading API",
    description="Institutional-Grade AI Quant Trading Platform API",
    version="3.0.0",
    lifespan=lifespan,
)


# --------------------------------------------------
# Helper — access services from any endpoint
# --------------------------------------------------


def _svc(request: Request) -> AppServices:
    """Return the AppServices instance from the request."""
    return request.app.state.services


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


class AddSecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Security headers
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # Keep CSP strict: no global unsafe-eval/unsafe-inline for scripts.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://unpkg.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https://static.tradingview.com; "
            "connect-src 'self' ws: wss: https://api.binance.com https://api.coingecko.com; "
            "frame-src 'self' https://s.tradingview.com;"
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


app.add_middleware(AddSecurityHeadersMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(RateLimiterMiddleware, max_requests=60, window_seconds=60)

# --------------------------------------------------
# CORS Configuration
# --------------------------------------------------

cors_allowed_origins = [
    origin.strip()
    for origin in str(getattr(settings, "cors_allowed_origins", "") or "").split(",")
    if origin.strip()
]

# Explicitly add production and local domains
default_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3005",
    "http://127.0.0.1:3005",
    "https://visiontrading.vercel.app",
    "https://vision-ai-5qm1.onrender.com"
]

for origin in default_origins:
    if origin not in cors_allowed_origins:
        cors_allowed_origins.append(origin)

raw_cors_regex = str(getattr(settings, "cors_allow_origin_regex", "") or "").strip()
cors_allow_origin_regex = raw_cors_regex or r"https://visiontrading.*\.vercel\.app"

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins,
    allow_origin_regex=cors_allow_origin_regex,
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
        content={
            "error": "Internal server error",
            "message": "An internal server error occurred",
            "fallback": True,
        },
    )


# NOTE: Preflight OPTIONS handling is done by CORSMiddleware above.

# --------------------------------------------------
# Routers
# --------------------------------------------------

app.include_router(auth_router, prefix="/auth")
app.include_router(admin_router, prefix="/admin")


# --------------------------------------------------
# Request Models
# --------------------------------------------------


class DataRequest(BaseModel):
    symbol: str = Field(default="BTCUSDT", max_length=20)
    period: str = Field(default="1y", max_length=5)


class TrainRequest(BaseModel):
    symbol: str = Field(default="BTCUSDT", max_length=20)


class PredictRequest(BaseModel):
    symbol: str = Field(default="BTCUSDT", max_length=20)
    horizon: int = Field(default=5, ge=1, le=60)


class BacktestRequest(BaseModel):
    symbol: str = Field(default="BTCUSDT", max_length=20)
    period: str = Field(default="1y", max_length=5)
    initial_capital: float = Field(default=100000.0, gt=0)
    commission_bps: float = Field(default=15.0, ge=0, le=100)
    spread_bps: float = Field(default=8.0, ge=0, le=100)
    slippage_bps: float = Field(default=6.0, ge=0, le=100)
    latency_bps: float = Field(default=2.0, ge=0, le=50)


class PaperTradingRequest(BaseModel):
    symbol: str = Field(default="BTC/USDT", max_length=20)
    initial_cash: float = Field(default=10000.0, gt=0)
    interval_seconds: int = Field(default=300, ge=10, le=86400)


class ManualTradeRequest(BaseModel):
    symbol: str = Field(default="BTC/USDT", max_length=20)
    side: str = Field(default="buy", pattern="^(buy|sell)$")
    size_usd: float = Field(default=100.0, gt=0)


class ClosePositionRequest(BaseModel):
    symbol: str = Field(default="BTC/USDT", max_length=20)
# --------------------------------------------------
# Internal helpers
# --------------------------------------------------


def _get_market_data(svc: AppServices, symbol: str):
    """Fetch market data with a 30-second cache."""
    if svc.cached_df is not None and time.time() - svc.last_update < 30:
        return svc.cached_df

    try:
        df = svc.fetcher.fetch(symbol)
        if df is None or df.empty:
            return svc.cached_df if svc.cached_df is not None else pd.DataFrame()

        df = svc.engineer.add_all_indicators(df)
        df = df.dropna()

        svc.cached_df = df
        svc.last_update = time.time()
        return df
    except Exception as e:
        logger.error("Market data fetch error: %s", e)
        return svc.cached_df if svc.cached_df is not None else pd.DataFrame()


def _get_trainer(svc: AppServices):
    """Lazy-init the model trainer."""
    if svc.trainer is None:
        from backend.src.models.trainer import ModelTrainer

        svc.trainer = ModelTrainer()
    return svc.trainer


def _get_sentiment_engine(svc: AppServices):
    """Lazy-init sentiment engine (FinBERT is heavy)."""
    if svc.sentiment_engine is None:
        try:
            from backend.src.sentiment.sentiment_engine import SentimentEngine

            svc.sentiment_engine = SentimentEngine()
        except Exception as e:
            logger.warning("SentimentEngine init failed: %s", e)
            return None
    return svc.sentiment_engine


def _resolve_live_adapter(svc: AppServices):
    """Resolve a live-capable adapter for safety checks when possible."""
    try:
        if svc.paper_trader and hasattr(svc.paper_trader, "adapter"):
            adapter = svc.paper_trader.adapter
            from backend.src.exchange.exchange_adapter import PaperAdapter

            if adapter is not None and not isinstance(adapter, PaperAdapter):
                return adapter
    except Exception:
        pass

    if (
        settings.trading_mode == "live"
        and settings.binance_api_key
        and settings.binance_secret
    ):
        try:
            from backend.src.exchange.exchange_adapter import BinanceAdapter

            return BinanceAdapter(
                api_key=settings.binance_api_key,
                secret=settings.binance_secret,
                testnet=settings.live_use_testnet,
            )
        except Exception as e:
            logger.warning("Live adapter init failed during preflight: %s", e)
    return None


def _build_live_readiness_report(svc: AppServices) -> Dict:
    """Institutional-style readiness gate for enabling live trading."""
    from backend.src.execution.live_safety import LiveTradingSafety

    blocked_reasons = []
    adapter = _resolve_live_adapter(svc)
    safety = LiveTradingSafety(
        settings=settings,
        risk_manager=svc.risk_manager,
        adapter=adapter,
    )
    preflight = safety.get_report_dict()
    if not preflight.get("all_passed", False):
        blocked_reasons.extend(preflight.get("blocked_reasons", []))

    health = svc.health_monitor.check_all(
        predictor=svc.predictor,
        paper_trader=svc.paper_trader,
        risk_manager=svc.risk_manager,
        cached_df=svc.cached_df,
        last_data_update=svc.last_update,
    )
    components = health.get("components", {})
    market_data_healthy = bool(components.get("market_data", {}).get("healthy", False))
    risk_healthy = bool(components.get("risk_manager", {}).get("healthy", False))
    if not market_data_healthy:
        blocked_reasons.append("Market data is stale/unavailable")
    if not risk_healthy:
        blocked_reasons.append("Risk manager is unhealthy or kill switch is active")

    execution_guardrails = {
        "available": False,
        "tripped": False,
        "trip_reason": "",
        "message": "Execution engine not running; guardrails will be enforced at runtime",
    }
    if (
        svc.paper_trader
        and hasattr(svc.paper_trader, "execution")
        and hasattr(svc.paper_trader.execution, "get_circuit_breaker_status")
    ):
        breaker = svc.paper_trader.execution.get_circuit_breaker_status()
        execution_guardrails = {
            "available": True,
            "tripped": bool(breaker.get("tripped", False)),
            "trip_reason": breaker.get("trip_reason", ""),
            "message": "Execution circuit breaker active",
            "status": breaker,
        }
        if execution_guardrails["tripped"]:
            blocked_reasons.append(
                f"Execution circuit breaker is tripped: {execution_guardrails['trip_reason']}"
            )

    jwt_ok = len((settings.jwt_secret or "").strip()) >= 32
    api_keys_ok = bool(settings.binance_api_key and settings.binance_secret)
    secrets_ready = jwt_ok and api_keys_ok
    if not secrets_ready:
        if not jwt_ok:
            blocked_reasons.append(
                "JWT secret does not meet minimum security requirements"
            )
        if not api_keys_ok:
            blocked_reasons.append("Exchange API keys are missing")

    score_components = {
        "preflight": 100 if preflight.get("all_passed", False) else 0,
        "risk_and_data_health": 100 if (market_data_healthy and risk_healthy) else 0,
        "execution_guardrails": (
            100 if not execution_guardrails.get("tripped", False) else 0
        ),
        "secrets": 100 if secrets_ready else 0,
    }
    overall_score = sum(score_components.values()) / max(len(score_components), 1)

    all_ready = (
        preflight.get("all_passed", False)
        and market_data_healthy
        and risk_healthy
        and not execution_guardrails.get("tripped", False)
        and secrets_ready
    )

    return {
        "all_ready": all_ready,
        "overall_score": round(overall_score, 2),
        "score_components": score_components,
        "blocked_reasons": blocked_reasons,
        "preflight": preflight,
        "health": {
            "status": health.get("status", "unknown"),
            "market_data_healthy": market_data_healthy,
            "risk_manager_healthy": risk_healthy,
        },
        "execution_guardrails": execution_guardrails,
        "security": {
            "jwt_ok": jwt_ok,
            "api_keys_ok": api_keys_ok,
        },
    }


def _build_system_readiness_report(svc: AppServices) -> Dict:
    """System-wide institutional readiness scorecard with real execution metrics."""
    live_readiness = _build_live_readiness_report(svc)

    from backend.src.monitoring.execution_monitor import ExecutionMonitor
    from backend.src.monitoring.risk_monitor import RiskMonitor
    from backend.src.safety.live_guard import LiveGuard

    execution_monitor = ExecutionMonitor()
    risk_monitor = RiskMonitor()
    live_guard = LiveGuard()

    # Get real execution metrics from collector (or zeros if no data yet)
    exec_metrics = {
        "avg_latency_ms": 0.0,
        "avg_slippage_bps": 0.0,
    }
    if svc.execution_metrics_collector:
        try:
            current = svc.execution_metrics_collector.get_current_metrics()
            exec_metrics = {
                "avg_latency_ms": current.get("avg_latency_ms", 0.0),
                "avg_slippage_bps": current.get("avg_slippage_bps", 0.0),
            }
        except Exception as e:
            logger.warning("Failed to get execution metrics: %s", e)

    execution_quality = execution_monitor.assess(exec_metrics)

    # Get real risk state from portfolio and risk manager
    risk_state = {
        "drawdown_pct": (
            getattr(svc.portfolio_manager, "max_drawdown", 0.0)
            if svc.portfolio_manager
            else 0.0
        ),
        "var_breach": (
            bool(getattr(svc.risk_manager, "kill_switch", False))
            if svc.risk_manager
            else False
        ),
        "exposure_ok": (
            not bool(getattr(svc.risk_manager, "kill_switch", False))
            if svc.risk_manager
            else False
        ),
    }
    risk_health = risk_monitor.assess(risk_state)

    guard = live_guard.evaluate(live_readiness, risk_health, execution_quality)

    # Score components with quality-aware mapping
    components = {
        "live_readiness": (
            100.0
            if live_readiness.get("all_ready", False)
            else float(live_readiness.get("overall_score", 0.0))
        ),
        "risk_health": (
            100.0
            if risk_health.get("status") == "healthy"
            else 60.0 if risk_health.get("status") == "warning" else 20.0
        ),
        "execution_quality": (
            100.0
            if execution_quality.get("quality") == "excellent"
            else (
                90.0
                if execution_quality.get("quality") == "good"
                else 60.0 if execution_quality.get("quality") == "degraded" else 20.0
            )
        ),
        "live_guard": 100.0 if guard.get("allow_live", False) else 0.0,
    }
    overall = sum(components.values()) / max(len(components), 1)

    return {
        "institutional_ready": overall >= 90.0 and guard.get("allow_live", False),
        "score": round(overall, 2),
        "target_threshold": 90.0,
        "components": components,
        "live_guard": guard,
        "live_readiness": live_readiness,
        "risk_monitor": risk_health,
        "execution_monitor": execution_quality,
        "execution_metrics": exec_metrics,
    }


def _service_get_json(
    request: Request,
    service_base_url: Optional[str],
    endpoint_path: str,
    params: Optional[dict] = None,
):
    """Best-effort GET delegation to extracted services with monolith fallback."""
    if not service_base_url:
        return None

    try:
        req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        target = urljoin(service_base_url.rstrip("/") + "/", endpoint_path.lstrip("/"))
        response = requests.get(
            target,
            params=params,
            timeout=settings.internal_service_timeout_seconds,
            headers={"X-Correlation-ID": req_id, "X-Request-ID": req_id},
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.warning("Service delegation failed for %s: %s", endpoint_path, e)
        return None


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
async def health(request: Request):
    svc = _svc(request)
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "predictor": svc.predictor is not None,
        "paper_trading": svc.paper_trader is not None
        and getattr(svc.paper_trader, "running", False),
        "mode": settings.trading_mode,
    }


@app.get("/health/detailed")
async def health_detailed(request: Request):
    svc = _svc(request)
    return svc.health_monitor.check_all(
        predictor=svc.predictor,
        paper_trader=svc.paper_trader,
        risk_manager=svc.risk_manager,
        cached_df=svc.cached_df,
        last_data_update=svc.last_update,
    )


# ==================================================
# DATA
# ==================================================


@app.post("/data/fetch")
async def fetch_data(request_body: DataRequest, request: Request):
    svc = _svc(request)
    try:
        symbol = request_body.symbol.replace("/", "").replace("USDT", "/USDT")
        df = svc.fetcher.fetch(symbol)

        if df is None or df.empty:
            raise HTTPException(404, "No data found")

        return {
            "symbol": request_body.symbol,
            "rows": len(df),
            "columns": list(df.columns),
        }
    except Exception as e:
        logger.error("Data fetch error: %s", e)
        raise HTTPException(500, str(e))


@app.get("/market/realtime")
async def market_realtime(request: Request, symbol: str = "BTCUSDT"):
    svc = _svc(request)
    if not svc.realtime_feed:
        raise HTTPException(503, "Realtime feed unavailable")
    await svc.realtime_feed.ensure_symbol(symbol)
    return svc.realtime_feed.get_snapshot(symbol)


@app.get("/market/history")
async def market_history(
    request: Request, symbol: str = "BTCUSDT", timeframe: str = "1m", limit: int = 200
):
    svc = _svc(request)
    try:
        clean_symbol = symbol.replace("/", "").replace("USDT", "/USDT")
        df = svc.fetcher.fetch(clean_symbol, timeframe=timeframe, limit=limit)
        if df is None or df.empty:
            raise HTTPException(404, "No market history available")
        candles = []
        for idx, row in df.tail(limit).iterrows():
            candles.append(
                {
                    "time": int(pd.Timestamp(idx).timestamp()),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                }
            )
        return {"symbol": symbol, "timeframe": timeframe, "candles": candles}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Market history error: {e}", exc_info=True)
        raise HTTPException(500, str(e))


# ==================================================
# FEATURES
# ==================================================


@app.post("/features/generate")
async def generate_features(request_body: DataRequest, request: Request):
    svc = _svc(request)
    try:
        symbol = request_body.symbol.replace("/", "").replace("USDT", "/USDT")
        df = svc.fetcher.fetch(symbol)
        df = svc.engineer.add_all_indicators(df)

        return {
            "symbol": request_body.symbol,
            "rows": len(df),
            "features": list(df.columns),
            "feature_count": len(df.columns),
        }
    except Exception as e:
        logger.error("Feature generation error: %s", e)
        raise HTTPException(500, str(e))


# ==================================================
# MODEL TRAINING
# ==================================================


@app.post("/model/train", dependencies=[Depends(get_current_user)])
async def train_model(request_body: TrainRequest, request: Request):
    svc = _svc(request)
    try:
        t = _get_trainer(svc)
        symbol = request_body.symbol.replace("/", "").replace("USDT", "/USDT")
        df = svc.fetcher.fetch(symbol)
        df = svc.engineer.add_all_indicators(df)
        df = df.dropna()

        result = t.train(df)
        t.save("trading_model")

        return {
            "status": "model trained",
            "rows": len(df),
            "metrics": t.metrics,
            "top_features": t.metrics.get("top_features", [])[:10],
        }
    except Exception as e:
        logger.error("Model training error: %s", e)
        raise HTTPException(500, str(e))


# ==================================================
# PREDICTION + QUANT INTELLIGENCE
# ==================================================


async def _run_prediction(svc: AppServices, symbol: str, horizon: int):
    """Shared prediction logic used by both GET and POST endpoints."""
    try:
        clean_symbol = symbol.replace("/", "").replace("USDT", "/USDT")
        logger.info("Prediction requested for %s (horizon=%d)", symbol, horizon)

        df = _get_market_data(svc, clean_symbol)
        if df is None or df.empty:
            return {
                "symbol": symbol,
                "signal": "HOLD",
                "confidence": 0.5,
                "position_size": 0,
                "message": "market data unavailable",
            }

        # ML Predictions
        preds = (
            svc.predictor.predict_symbol(symbol=clean_symbol, horizon=horizon)
            if svc.predictor
            else []
        )
        if not preds:
            preds = [
                {
                    "step": 1,
                    "direction": "HOLD",
                    "probability": 0.5,
                    "confidence": 0.5,
                    "regime": "unknown",
                }
            ]

        probability = preds[0]["probability"]

        clean_key = clean_symbol.replace("/", "")
        history = svc.prediction_probability_history.get(clean_key)
        if history is None:
            history = {
                "baseline": deque(maxlen=400),
                "current": deque(maxlen=120),
            }
            svc.prediction_probability_history[clean_key] = history

        history["current"].append(float(probability))
        if len(history["baseline"]) < 120:
            history["baseline"].append(float(probability))

        # Regime Detection
        regime = svc.regime_detector.get_regime(df)
        strategy = svc.strategy_selector.select_strategy(regime)

        # Volatility for strategy signal
        _volatility = 0.0
        if df is not None and "volatility_20" in df.columns:
            _volatility = float(df["volatility_20"].iloc[-1])

        # Strategy Signal (v2 engine: probability, regime, volatility)
        strategy_result = svc.strategy_engine.generate_detailed_signal(
            probability=probability,
            regime=regime,
            volatility=_volatility,
        )

        # Sentiment (lazy-loaded)
        _se = _get_sentiment_engine(svc)
        sentiment = _se.get_sentiment() if _se else {"score": 0.0, "label": "neutral"}
        sentiment_score = sentiment.get("score", 0)

        market_snapshot = None
        if svc.realtime_feed:
            await svc.realtime_feed.ensure_symbol(clean_symbol)
            market_snapshot = svc.realtime_feed.get_snapshot(clean_symbol)

        # Signal Fusion
        signal_data = svc.signal_engine.generate_signal(
            df,
            preds[0] if preds else {"probability": 0.5},
            sentiment_score=sentiment_score,
            regime=regime,
            strategy_result=strategy_result,
        )

        meta_alpha = None
        if svc.meta_alpha_engine:
            meta_alpha = svc.meta_alpha_engine.infer(
                prediction=preds[0] if preds else {"probability": 0.5},
                strategy_result=strategy_result,
                sentiment_score=sentiment_score,
                regime=regime,
                market_snapshot=market_snapshot,
            )

        drift_summary = {
            "drift_detected": False,
            "reason": "insufficient_history",
        }
        if (
            svc.drift_detector
            and len(history["baseline"]) >= 80
            and len(history["current"]) >= 40
        ):
            import numpy as np

            drift_summary = svc.drift_detector.evaluate(
                baseline_scores=np.array(history["baseline"], dtype=float),
                current_scores=np.array(history["current"], dtype=float),
                baseline_metric=None,
                current_metric=None,
            )

        # Confidence
        confidence = svc.confidence_engine.calculate_confidence(
            probability=probability,
            regime=regime,
            volatility_regime=regime.get("volatility", "low_volatility"),
        )

        # Risk
        risk = svc.risk_score_engine.calculate_risk(df)

        # Position Sizing
        base_position = 0.1
        position_size = base_position * confidence
        if isinstance(risk, dict) and risk.get("risk_level") == "high":
            position_size *= 0.5
        position_size = round(position_size, 3)

        final_signal = meta_alpha["signal"] if meta_alpha else signal_data["direction"]
        final_score = meta_alpha["alpha_score"] if meta_alpha else signal_data["score"]
        final_signal_confidence = (
            meta_alpha["confidence"] if meta_alpha else signal_data["confidence"]
        )

        rejection_reasons = []
        if drift_summary.get("drift_detected"):
            rejection_reasons.append("drift_detected")
        if market_snapshot and market_snapshot.get("stale"):
            rejection_reasons.append("stale_market_snapshot")

        alpha_score = float((meta_alpha or {}).get("alpha_score", final_score) or 0.5)
        if final_signal in ("BUY", "SELL") and alpha_score < 0.6:
            rejection_reasons.append("alpha_below_entry_threshold")

        if rejection_reasons:
            final_signal = "HOLD"
            position_size = 0.0

        if final_signal in ("BUY", "SELL") and final_signal_confidence < 0.55:
            position_size = round(position_size * 0.5, 3)

        return {
            "symbol": symbol,
            "predictions": preds,
            "signal": final_signal,
            "alpha_score": alpha_score,
            "signal_score": final_score,
            "signal_confidence": final_signal_confidence,
            "components": signal_data["signals"],
            "strategy": strategy_result,
            "confidence": confidence,
            "risk": risk,
            "position_size": position_size,
            "regime": regime,
            "meta_alpha": meta_alpha,
            "drift": drift_summary,
            "rejection_reasons": rejection_reasons,
            "market_snapshot": market_snapshot,
            "sentiment": {
                "score": sentiment_score,
                "label": sentiment.get("label", "neutral"),
            },
        }
    except Exception as e:
        logger.error(f"Prediction error: {e}", exc_info=True)
        return {
            "symbol": symbol,
            "signal": "HOLD",
            "confidence": 0.5,
            "position_size": 0,
            "message": "fallback prediction",
        }


@app.post("/model/predict", dependencies=[Depends(get_current_user)])
async def predict(request_body: PredictRequest, request: Request):
    svc = _svc(request)
    return await _run_prediction(svc, request_body.symbol, request_body.horizon)


@app.get("/model/predict", dependencies=[Depends(get_current_user)])
async def predict_get(request: Request, symbol: str = "BTCUSDT", horizon: int = 5):
    """GET variant of predict — accepts query params for browser/fetch compatibility."""
    svc = _svc(request)
    logger.info("GET /model/predict called for %s", symbol)
    return await _run_prediction(svc, symbol, horizon)


# ==================================================
# BACKTEST
# ==================================================


@app.post("/backtest/run", dependencies=[Depends(get_current_user)])
async def run_backtest(request_body: BacktestRequest, request: Request):
    svc = _svc(request)
    try:
        from backend.src.research.backtesting_engine import BacktestEngine

        engine = BacktestEngine(
            initial_capital=request_body.initial_capital,
            commission_pct=request_body.commission_bps / 10000.0,
            spread_bps=request_body.spread_bps,
            slippage_bps=request_body.slippage_bps,
            latency_bps=request_body.latency_bps,
        )
        symbol = request_body.symbol.replace("/", "").replace("USDT", "/USDT")
        results = engine.run_from_symbol(symbol=symbol, period=request_body.period)
        return {"symbol": request_body.symbol, "results": results}
    except Exception as e:
        logger.error("Backtest error: %s", e)
        raise HTTPException(500, str(e))


# ==================================================
# PORTFOLIO
# ==================================================


@app.get("/portfolio/status", dependencies=[Depends(get_current_user)])
async def portfolio_status(request: Request):
    delegated = _service_get_json(
        request, settings.portfolio_service_url, "/portfolio/status"
    )
    if delegated is not None:
        return delegated

    svc = _svc(request)
    cached = svc.cache.get_json("portfolio:latest") if svc.cache else None
    if cached:
        return cached
    return svc.portfolio_manager.get_portfolio()


@app.get("/portfolio/performance", dependencies=[Depends(get_current_user)])
async def portfolio_performance(request: Request):
    delegated = _service_get_json(
        request,
        settings.portfolio_service_url,
        "/portfolio/performance",
    )
    if delegated is not None:
        return delegated

    svc = _svc(request)
    try:
        cached = svc.cache.get_json("performance:latest") if svc.cache else None
        if cached:
            return cached
        return svc.portfolio_manager.get_performance()
    except Exception as e:
        logger.error(f"Portfolio performance error: {e}", exc_info=True)
        return {"total_return": 0, "win_rate": 0, "max_drawdown": 0, "total_trades": 0}


# ==================================================
# REGIME
# ==================================================


@app.get("/regime/current", dependencies=[Depends(get_current_user)])
async def get_regime(request: Request, symbol: str = "BTC/USDT"):
    svc = _svc(request)
    try:
        df = _get_market_data(svc, symbol)
        return svc.regime_detector.get_regime(df)
    except Exception as e:
        logger.error(f"Regime detection error: {e}", exc_info=True)
        return {"label": "unknown", "trend": "default", "volatility": "unknown"}


# ==================================================
# SENTIMENT
# ==================================================


@app.get("/sentiment/current", dependencies=[Depends(get_current_user)])
async def get_sentiment(request: Request):
    svc = _svc(request)
    try:
        _se = _get_sentiment_engine(svc)
        if _se:
            return _se.get_sentiment()
        return {"score": 0.0, "label": "neutral", "message": "Sentiment engine loading"}
    except Exception as e:
        logger.error(f"Sentiment analysis error: {e}", exc_info=True)
        return {"score": 0.0, "label": "neutral"}


# ==================================================
# RISK
# ==================================================


@app.get("/risk/status", dependencies=[Depends(get_current_user)])
async def risk_status(request: Request, symbol: str = "BTC/USDT"):
    delegated = _service_get_json(
        request,
        settings.risk_service_url,
        "/risk/status",
        params={"symbol": symbol},
    )
    if delegated is not None:
        return delegated

    svc = _svc(request)
    try:
        df = _get_market_data(svc, symbol)
        risk = svc.risk_score_engine.calculate_risk(df)
        risk["kill_switch"] = (
            svc.risk_manager.kill_switch_active if svc.risk_manager else False
        )
        risk["events"] = (
            svc.risk_manager.get_events(limit=10) if svc.risk_manager else []
        )
        return risk
    except Exception as e:
        logger.error(f"Risk status error: {e}", exc_info=True)
        return {
            "risk_level": "low",
            "risk_score": 0.2,
            "kill_switch": False,
            "events": [],
        }


# ==================================================
# STRATEGIES
# ==================================================


@app.get("/strategies/list", dependencies=[Depends(get_current_user)])
async def list_strategies(request: Request):
    svc = _svc(request)
    # v2 StrategyEngine: model-driven, no legacy strategy map
    stats = svc.strategy_engine.get_signal_stats()
    return {
        "strategies": [
            {
                "name": "Alpha Model",
                "key": "alpha_model",
                "active": True,
                "weight": 1.0,
                "type": "model_driven",
                "thresholds": {
                    "long": svc.strategy_engine.long_threshold,
                    "short": svc.strategy_engine.short_threshold,
                    "min_confidence": svc.strategy_engine.min_confidence,
                },
            }
        ],
        "total": 1,
        "signal_stats": stats,
    }


# ==================================================
# PAPER TRADING
# ==================================================


@app.post("/paper-trading/start", dependencies=[Depends(get_current_user)])
async def start_paper_trading(request_body: PaperTradingRequest, request: Request):
    svc = _svc(request)

    if svc.paper_trader and getattr(svc.paper_trader, "running", False):
        return {"status": "already_running", "cycles": svc.paper_trader.cycle_count}

    from backend.src.workers.trading_loop import TradingLoop

    svc.paper_trader = TradingLoop(
        symbol=request_body.symbol,
        initial_cash=request_body.initial_cash,
        metrics_collector=svc.execution_metrics_collector,
    )

    svc.paper_trader.interval_seconds = request_body.interval_seconds

    if svc.worker_manager is None:
        from backend.src.workers.worker_manager import WorkerManager

        svc.worker_manager = WorkerManager()

    svc.worker_manager.register(
        "paper_trading", svc.paper_trader, auto_restart=True, max_restarts=5
    )
    await svc.worker_manager.start_worker("paper_trading")

    return {"status": "started", "symbol": request_body.symbol}


@app.post("/paper-trading/stop", dependencies=[Depends(get_current_user)])
async def stop_paper_trading(request: Request):
    svc = _svc(request)
    if svc.paper_trader:
        if svc.worker_manager:
            await svc.worker_manager.stop_worker("paper_trading")
        else:
            svc.paper_trader.stop()
        return {"status": "stopped", "cycles": svc.paper_trader.cycle_count}
    return {"status": "not_running"}


@app.get("/paper-trading/status", dependencies=[Depends(get_current_user)])
async def paper_trading_status(request: Request):
    svc = _svc(request)
    try:
        # Try cache first (worker heartbeat)
        cached_hb = svc.cache.get_json("worker:heartbeat") if svc.cache else None
        if cached_hb and cached_hb.get("running"):
            perf = svc.cache.get_json("performance:latest") or {}
            port = svc.cache.get_json("portfolio:latest") or {}
            return {
                "running": True,
                "mode": cached_hb.get("mode", "paper"),
                "symbol": cached_hb.get("symbol", ""),
                "cycle_count": cached_hb.get("cycle", 0),
                "performance": perf,
                "portfolio": port,
            }
        if svc.paper_trader is None:
            return {"status": "not_initialized"}
        status = svc.paper_trader.get_status()
        if svc.worker_manager:
            status["workers"] = svc.worker_manager.get_status()
        return status
    except Exception as e:
        logger.error(f"Paper trading status error: {e}", exc_info=True)
        return {"status": "error", "message": "Status unavailable"}


@app.get("/workers/status", dependencies=[Depends(get_current_user)])
async def workers_status(request: Request):
    svc = _svc(request)
    if svc.worker_manager is None:
        return {"total_workers": 0, "running": 0, "workers": {}}
    return svc.worker_manager.get_status()


# ==================================================
# LIVE TRADING
# ==================================================


@app.get("/live-trading/preflight", dependencies=[Depends(get_current_user)])
async def live_trading_preflight(request: Request):
    """Run pre-flight safety checks for live trading."""
    svc = _svc(request)
    from backend.src.execution.live_safety import LiveTradingSafety

    adapter = _resolve_live_adapter(svc)
    safety = LiveTradingSafety(
        settings=settings,
        risk_manager=svc.risk_manager,
        adapter=adapter,
    )
    return safety.get_report_dict()


@app.get("/live-trading/readiness", dependencies=[Depends(get_current_user)])
async def live_trading_readiness(request: Request):
    """Institutional readiness gate for live trading deployment."""
    svc = _svc(request)
    return _build_live_readiness_report(svc)


@app.get("/system/readiness")
async def system_readiness(request: Request):
    """Institutional system readiness endpoint (target >= 90)."""
    svc = _svc(request)
    return _build_system_readiness_report(svc)


@app.get("/system/performance")
async def system_performance(request: Request):
    return await portfolio_performance(request)


@app.get("/system/risk")
async def system_risk(request: Request, symbol: str = "BTC/USDT"):
    return await risk_status(request, symbol=symbol)


@app.get("/system/meta_alpha")
async def system_meta_alpha(
    request: Request, symbol: str = "BTCUSDT", horizon: int = 5
):
    svc = _svc(request)
    prediction = await _run_prediction(svc, symbol, horizon)
    return {
        "symbol": symbol,
        "meta_alpha": prediction.get("meta_alpha"),
        "market_snapshot": prediction.get("market_snapshot"),
        "signal": prediction.get("signal"),
    }


@app.post("/live-trading/enable", dependencies=[Depends(get_current_user)])
async def enable_live_trading(request: Request):
    """Enable live trading (requires all pre-flight checks to pass)."""
    svc = _svc(request)
    readiness = _build_live_readiness_report(svc)

    if not readiness.get("all_ready", False):
        raise HTTPException(
            403, f"Live readiness gate failed: {readiness.get('blocked_reasons', [])}"
        )

    return {
        "status": "live_trading_ready",
        "message": "Live readiness gate passed. System is eligible for live order flow.",
        "readiness_score": readiness.get("overall_score", 0),
    }


# ==================================================
# MANUAL TRADING
# ==================================================

@app.post("/trading/buy", dependencies=[Depends(get_current_user)])
async def manual_buy(request: Request, body: ManualTradeRequest):
    """Execute a manual buy order."""
    svc = _svc(request)
    if not svc.paper_trader:
        raise HTTPException(status_code=400, detail="Paper trading not active")
    execution = getattr(svc.paper_trader, "execution", None)
    order_manager = getattr(execution, "order_manager", None) if execution is not None else None
    if execution is None or order_manager is None:
        raise HTTPException(status_code=400, detail="Trading execution not available")
        
    try:
        df = svc.fetcher.fetch(body.symbol)
        if df is None or df.empty:
            raise HTTPException(status_code=400, detail="Could not fetch market price")
            
        price = float(df["close"].iloc[-1])
        quantity = body.size_usd / price
        
        order = order_manager.submit_market_order(
            symbol=body.symbol, side="buy", quantity=quantity, price=price
        )
        
        if order.status == "filled":
            svc.portfolio_manager.open_position(
                symbol=body.symbol,
                side="long",
                quantity=quantity,
                price=order.filled_price,
                strategy_name="manual",
                metadata={"source": "manual"},
            )
            return {"status": "success", "message": "Buy order executed", "order": order.__dict__}
        else:
            raise HTTPException(status_code=400, detail=f"Order rejected: {order.error}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error executing manual buy: %s", e)
        raise HTTPException(status_code=500, detail="Manual buy failed")


@app.post("/trading/sell", dependencies=[Depends(get_current_user)])
async def manual_sell(request: Request, body: ManualTradeRequest):
    """Execute a manual sell (short) order."""
    svc = _svc(request)
    if not svc.paper_trader:
        raise HTTPException(status_code=400, detail="Paper trading not active")
    execution = getattr(svc.paper_trader, "execution", None)
    order_manager = getattr(execution, "order_manager", None) if execution is not None else None
    if execution is None or order_manager is None:
        raise HTTPException(status_code=400, detail="Trading execution not available")
        
    try:
        df = svc.fetcher.fetch(body.symbol)
        if df is None or df.empty:
            raise HTTPException(status_code=400, detail="Could not fetch market price")
            
        price = float(df["close"].iloc[-1])
        quantity = body.size_usd / price
        
        order = order_manager.submit_market_order(
            symbol=body.symbol, side="sell", quantity=quantity, price=price
        )
        
        if order.status == "filled":
            svc.portfolio_manager.open_position(
                symbol=body.symbol,
                side="short",
                quantity=quantity,
                price=order.filled_price,
                strategy_name="manual",
                metadata={"source": "manual"},
            )
            return {"status": "success", "message": "Sell order executed", "order": order.__dict__}
        else:
            raise HTTPException(status_code=400, detail=f"Order rejected: {order.error}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error executing manual sell: %s", e)
        raise HTTPException(status_code=500, detail="Manual sell failed")


@app.post("/trading/close", dependencies=[Depends(get_current_user)])
async def manual_close(request: Request, body: ClosePositionRequest):
    """Close an open position."""
    svc = _svc(request)
    if not svc.paper_trader:
        raise HTTPException(status_code=400, detail="Paper trading not active")
    execution = getattr(svc.paper_trader, "execution", None)
    order_manager = getattr(execution, "order_manager", None) if execution is not None else None
    if execution is None or order_manager is None:
        raise HTTPException(status_code=400, detail="Trading execution not available")
        
    positions = svc.portfolio_manager.get_portfolio().get("positions", {})
    position = positions.get(body.symbol)
    if not position:
        raise HTTPException(status_code=404, detail="No open position for symbol")
        
    try:
        df = svc.fetcher.fetch(body.symbol)
        if df is None or df.empty:
            raise HTTPException(status_code=400, detail="Could not fetch market price")
            
        price = float(df["close"].iloc[-1])
        quantity = position["quantity"]
        close_side = "sell" if position["side"] == "long" else "buy"
        
        order = order_manager.submit_market_order(
            symbol=body.symbol, side=close_side, quantity=quantity, price=price
        )
        
        if order.status == "filled":
            svc.portfolio_manager.close_position(symbol=body.symbol, price=order.filled_price)
            return {"status": "success", "message": "Position closed", "order": order.__dict__}
        else:
            raise HTTPException(status_code=400, detail=f"Order rejected: {order.error}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error executing manual close: %s", e)
        raise HTTPException(status_code=500, detail="Manual close failed")


# ==================================================
# ORDER TRACKING
# ==================================================


@app.get("/orders/active", dependencies=[Depends(get_current_user)])
async def active_orders(request: Request):
    svc = _svc(request)
    if svc.paper_trader is None:
        return {"orders": [], "message": "No trading loop active"}
    return {"orders": svc.paper_trader.execution.get_active_orders()}


@app.get("/orders/history", dependencies=[Depends(get_current_user)])
async def order_history(request: Request, limit: int = 50):
    svc = _svc(request)
    # Try reading from PostgreSQL for historical orders
    try:
        from backend.src.database.db import get_connection

        conn = get_connection()
        cur = None
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM trades ORDER BY timestamp DESC LIMIT %s", (limit,))
            rows = cur.fetchall()
        finally:
            if cur is not None:
                cur.close()
            release_connection(conn)
        if rows:
            orders = [
                {
                    "id": r[0],
                    "timestamp": r[-1],
                    "symbol": r[2],
                    "side": r[3],
                    "size": r[4],
                    "price": r[5],
                }
                for r in rows
            ]
            return {"orders": orders, "statistics": {"total_orders": len(orders)}}
    except Exception as e:
        logger.warning("DB order history fallback: %s", e)

    if svc.paper_trader is None:
        return {"orders": [], "message": "No trading loop active"}
    return {
        "orders": svc.paper_trader.execution.get_order_history(limit),
        "statistics": svc.paper_trader.execution.get_order_statistics(),
    }


@app.websocket("/ws/market")
async def market_stream(websocket: WebSocket, symbol: str = "BTCUSDT"):
    await _stream_channel(
        websocket=websocket,
        channel="market",
        symbol=symbol,
        interval_seconds=1.0,
        payload_builder=_build_market_payload,
    )


@app.websocket("/ws/signals")
async def signals_stream(websocket: WebSocket, symbol: str = "BTCUSDT"):
    """Real-time trading signals stream with confidence scores and regime detection."""
    await _stream_channel(
        websocket=websocket,
        channel="signals",
        symbol=symbol,
        interval_seconds=2.0,
        payload_builder=_build_signals_payload,
    )


@app.websocket("/ws/portfolio")
async def portfolio_stream(websocket: WebSocket):
    """Real-time portfolio updates with equity, cash, and position tracking."""
    await _stream_channel(
        websocket=websocket,
        channel="portfolio",
        symbol=None,
        interval_seconds=1.0,
        payload_builder=_build_portfolio_payload,
    )


@app.websocket("/ws/metrics")
async def metrics_stream(websocket: WebSocket):
    """Real-time performance metrics: win rate, Sharpe ratio, drawdown."""
    await _stream_channel(
        websocket=websocket,
        channel="metrics",
        symbol=None,
        interval_seconds=3.0,
        payload_builder=_build_metrics_payload,
    )


@app.websocket("/ws/live")
async def live_dashboard_stream(websocket: WebSocket, symbol: str = "BTCUSDT"):
    """Combined real-time stream: market + signals + portfolio + metrics."""
    await _stream_channel(
        websocket=websocket,
        channel="live",
        symbol=symbol,
        interval_seconds=1.0,
        payload_builder=_build_live_payload,
    )


def _normalize_symbol(symbol: Optional[str]) -> Optional[str]:
    if symbol is None:
        return None
    return symbol.strip().upper() if symbol.strip() else None


async def _cache_get_json(svc: AppServices, key: str):
    if not svc.cache:
        return None
    return await asyncio.to_thread(svc.cache.get_json, key)


async def _build_market_payload(svc: AppServices, symbol: Optional[str]) -> Dict:
    current_symbol = _normalize_symbol(symbol) or "BTCUSDT"
    if svc.realtime_feed:
        await svc.realtime_feed.ensure_symbol(current_symbol)
        snapshot = svc.realtime_feed.get_snapshot(current_symbol)
        if isinstance(snapshot, dict):
            snapshot["symbol"] = snapshot.get("symbol", current_symbol)
            return snapshot
    return {
        "symbol": current_symbol,
        "stale": True,
    }


async def _build_signals_payload(svc: AppServices, symbol: Optional[str]) -> Dict:
    current_symbol = _normalize_symbol(symbol) or "BTCUSDT"
    signal_data = {
        "symbol": current_symbol,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "direction": "HOLD",
        "confidence": 0.5,
        "probability": 0.5,
        "alpha_score": 0.5,
        "regime": "UNKNOWN",
        "market_state": "UNKNOWN",
        "strategy": "alpha_model",
    }

    cached = await _cache_get_json(svc, f"signal:{current_symbol}")
    if isinstance(cached, dict):
        signal_data.update(cached)

    if svc.signal_engine and hasattr(svc.signal_engine, "get_latest_signal"):
        try:
            latest = await asyncio.to_thread(
                svc.signal_engine.get_latest_signal, current_symbol
            )
            if isinstance(latest, dict):
                signal_data.update(latest)
        except Exception:
            pass

    return signal_data


async def _build_portfolio_payload(svc: AppServices, symbol: Optional[str]) -> Dict:
    del symbol
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cash": 0.0,
        "equity": 10000.0,
        "positions": {},
        "unrealized_pnl": 0.0,
        "realized_pnl": 0.0,
        "total_return": 0.0,
    }

    cached = await _cache_get_json(svc, "portfolio:latest")
    if isinstance(cached, dict):
        payload.update(cached)

    if svc.portfolio_manager:
        try:
            perf = await asyncio.to_thread(svc.portfolio_manager.get_performance)
            state = await asyncio.to_thread(svc.portfolio_manager.get_portfolio)
            payload.update(
                {
                    "equity": perf.get("current_equity", payload["equity"]),
                    "cash": state.get("cash", payload["cash"]),
                    "unrealized_pnl": state.get(
                        "unrealized_pnl", payload["unrealized_pnl"]
                    ),
                    "realized_pnl": state.get("realized_pnl", payload["realized_pnl"]),
                    "total_return": perf.get("total_return", payload["total_return"]),
                }
            )
        except Exception:
            pass

    return payload


async def _build_metrics_payload(svc: AppServices, symbol: Optional[str]) -> Dict:
    del symbol
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "win_rate": 0.0,
        "sharpe_ratio": 0.0,
        "max_drawdown": 0.0,
        "total_trades": 0,
        "profitable_trades": 0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
    }

    cached = await _cache_get_json(svc, "performance:latest")
    if isinstance(cached, dict):
        payload.update(cached)

    if svc.portfolio_manager:
        try:
            perf = await asyncio.to_thread(svc.portfolio_manager.get_performance)
            if isinstance(perf, dict):
                payload.update(
                    {
                        "win_rate": perf.get("win_rate", payload["win_rate"]),
                        "sharpe_ratio": perf.get(
                            "sharpe_ratio", payload["sharpe_ratio"]
                        ),
                        "max_drawdown": perf.get(
                            "max_drawdown", payload["max_drawdown"]
                        ),
                        "total_trades": perf.get(
                            "total_trades", payload["total_trades"]
                        ),
                    }
                )
        except Exception:
            pass

    return payload


async def _build_live_payload(svc: AppServices, symbol: Optional[str]) -> Dict:
    current_symbol = _normalize_symbol(symbol) or "BTCUSDT"
    market = await _build_market_payload(svc, current_symbol)
    signal = await _build_signals_payload(svc, current_symbol)
    portfolio = await _build_portfolio_payload(svc, None)
    metrics = await _build_metrics_payload(svc, None)
    return {
        "symbol": current_symbol,
        "market": market,
        "signal": signal,
        "portfolio": portfolio,
        "metrics": metrics,
    }


def _validate_ws_token(token: Optional[str]) -> bool:
    """Validate JWT token for WebSocket authentication."""
    if not token:
        return False
    try:
        from backend.src.auth.auth_service import decode_token
        payload = decode_token(token)
        return payload is not None
    except Exception:
        return False


async def _stream_channel(
    websocket: WebSocket,
    channel: str,
    symbol: Optional[str],
    interval_seconds: float,
    payload_builder,
) -> None:
    # -- WebSocket Authentication via query param token --
    token = websocket.query_params.get("token")
    if not _validate_ws_token(token):
        await websocket.close(code=4001, reason="Authentication required")
        return

    await websocket.accept()
    svc: AppServices = websocket.app.state.services
    current_symbol = _normalize_symbol(symbol)
    sequence = 0
    heartbeat_interval = 15.0
    client_idle_timeout = 90.0
    last_heartbeat_at = time.monotonic()
    last_client_message_at = time.monotonic()

    async def receive_client_messages() -> None:
        nonlocal last_client_message_at
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_json(), timeout=0.05)
                if isinstance(msg, dict) and msg.get("type") in {"ping", "pong", "ack"}:
                    last_client_message_at = time.monotonic()
            except asyncio.TimeoutError:
                return

    try:
        while True:
            now = time.monotonic()
            if now - last_client_message_at > client_idle_timeout:
                await websocket.close(code=1001, reason="Client idle timeout")
                break

            await receive_client_messages()

            sequence += 1
            payload = await payload_builder(svc, current_symbol)
            message = {
                "type": "data",
                "channel": channel,
                "symbol": current_symbol,
                "seq": sequence,
                "server_ts": datetime.now(timezone.utc).isoformat(),
                "data": payload,
            }
            await websocket.send_json(message)

            if now - last_heartbeat_at >= heartbeat_interval:
                await websocket.send_json(
                    {
                        "type": "heartbeat",
                        "channel": channel,
                        "symbol": current_symbol,
                        "seq": sequence,
                        "server_ts": datetime.now(timezone.utc).isoformat(),
                    }
                )
                last_heartbeat_at = now

            await asyncio.sleep(interval_seconds)
    except WebSocketDisconnect:
        logger.info("%s websocket disconnected for %s", channel, current_symbol)
    except Exception as exc:
        logger.warning("%s websocket error for %s: %s", channel, current_symbol, exc)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass


# ==================================================
# MODEL REGISTRY
# ==================================================


@app.get("/model/registry", dependencies=[Depends(get_current_user)])
async def get_model_registry(request: Request):
    svc = _svc(request)
    return {
        "active_version": svc.model_registry.active_version,
        "versions": svc.model_registry.get_all_versions(),
        "performance_history": svc.model_registry.get_performance_history(),
    }


# ==================================================
# NEWS AGGREGATION
# ==================================================


@app.get("/news")
async def get_news(request: Request, limit: int = 30):
    """Aggregated news from CryptoPanic, Finnhub, NewsAPI, CoinGecko."""
    svc = _svc(request)
    try:
        articles = svc.news_aggregator.get_news(limit=limit)
        return {"articles": articles, "count": len(articles)}
    except Exception as e:
        logger.error("News error: %s", e)
        return {"articles": [], "count": 0}


# ==================================================
# MARKET INTELLIGENCE
# ==================================================


@app.get("/market-intelligence")
async def market_intelligence():
    """CoinGecko trending coins + market overview."""
    try:
        import requests as req

        trending = req.get(
            "https://api.coingecko.com/api/v3/search/trending", timeout=10
        ).json()
        global_data = req.get(
            "https://api.coingecko.com/api/v3/global", timeout=10
        ).json()

        coins = []
        for item in trending.get("coins", [])[:10]:
            c = item.get("item", {})
            coins.append(
                {
                    "name": c.get("name"),
                    "symbol": c.get("symbol"),
                    "rank": c.get("market_cap_rank"),
                    "thumb": c.get("thumb"),
                }
            )

        gd = global_data.get("data", {})
        return {
            "trending_coins": coins,
            "total_market_cap_usd": gd.get("total_market_cap", {}).get("usd", 0),
            "total_volume_24h": gd.get("total_volume", {}).get("usd", 0),
            "btc_dominance": gd.get("market_cap_percentage", {}).get("btc", 0),
            "active_cryptocurrencies": gd.get("active_cryptocurrencies", 0),
        }
    except Exception as e:
        logger.error("Market intelligence error: %s", e)
        return {"trending_coins": [], "error": str(e)}


# ==================================================
# ALPHA RESEARCH
# ==================================================


@app.get("/research/feature-importance", dependencies=[Depends(get_current_user)])
async def feature_importance(request: Request):
    svc = _svc(request)
    t = _get_trainer(svc)
    if not t or not t.metadata.feature_importances:
        raise HTTPException(404, "No trained model - train first")
    return {"importance": t.get_feature_importance(top_n=20)}


# ==================================================
# MONITORING
# ==================================================


@app.get("/monitoring/metrics", dependencies=[Depends(get_current_user)])
async def get_monitoring_metrics(request: Request):
    """System metrics: latency, error rates, strategy performance, risk alerts."""
    svc = _svc(request)
    try:
        return svc.monitoring.get_metrics()
    except Exception as e:
        logger.error("Monitoring metrics error: %s", e)
        return {"status": "error", "message": str(e)}


# ==================================================
# Run Server
# ==================================================

if __name__ == "__main__":
    import os

    import uvicorn

    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("backend.src.api.main:app", host="0.0.0.0", port=port, reload=False)
