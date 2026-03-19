"""Strategy service for modular strategy evaluation and fusion outputs."""

from __future__ import annotations

from fastapi import Request

from backend.src.core.config import settings
from backend.src.core.event_stream import RedisStreamsBus
from backend.src.data.fetcher import DataFetcher
from backend.src.features.indicators import FeatureEngineer
from backend.src.models.predictor import Predictor
from backend.src.models.regime_detector import MarketRegimeDetector
from backend.src.services.shared.app_factory import create_service_app
from backend.src.strategy.strategy_engine import StrategyEngine

app = create_service_app("strategy-service")
_ = RedisStreamsBus(url=settings.redis_url, enabled=settings.redis_enabled)
fetcher = DataFetcher()
features = FeatureEngineer()
predictor = Predictor()
regime_detector = MarketRegimeDetector()
engine = StrategyEngine()


@app.get("/strategies/evaluate")
async def evaluate(symbol: str = "BTC/USDT", request: Request = None):
    df = features.add_all_indicators(fetcher.fetch(symbol), add_target=False)
    preds = predictor.predict_symbol(symbol, horizon=1)
    pred = preds[0] if preds else {"probability": 0.5}
    regime = regime_detector.get_regime(df)
    detail = engine.generate_detailed_signal(df, pred, regime)
    return {
        "symbol": symbol,
        "strategy_signal": detail,
        "correlation_id": getattr(request.state, "correlation_id", ""),
    }
