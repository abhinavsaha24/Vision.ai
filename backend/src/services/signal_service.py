"""Signal fusion service combining model output with sentiment and regime context."""

from __future__ import annotations

from fastapi import Request

from backend.src.contracts.events import EventEnvelope, EventName
from backend.src.core.config import settings
from backend.src.core.event_stream import RedisStreamsBus
from backend.src.data.fetcher import DataFetcher
from backend.src.features.indicators import FeatureEngineer
from backend.src.models.predictor import Predictor
from backend.src.models.regime_detector import MarketRegimeDetector
from backend.src.research.signal_engine import QuantSignalEngine
from backend.src.sentiment.sentiment_engine import SentimentEngine
from backend.src.services.shared.app_factory import create_service_app

app = create_service_app("signal-service")
bus = RedisStreamsBus(url=settings.redis_url, enabled=settings.redis_enabled)
fetcher = DataFetcher()
features = FeatureEngineer()
predictor = Predictor()
regime_detector = MarketRegimeDetector()
signal_engine = QuantSignalEngine()
sentiment_engine = SentimentEngine()


@app.get("/signals/generate")
async def generate_signal(symbol: str = "BTC/USDT", request: Request = None):
    df = fetcher.fetch(symbol)
    df = features.add_all_indicators(df, add_target=False)
    preds = predictor.predict_symbol(symbol, horizon=1)
    pred = preds[0] if preds else {"probability": 0.5}
    regime = regime_detector.get_regime(df)
    sentiment = sentiment_engine.get_sentiment().get("score", 0.0)
    signal = signal_engine.generate_signal(
        df, pred, sentiment_score=sentiment, regime=regime
    )
    event = EventEnvelope(
        source="signal-service",
        event_name=EventName.SIGNAL_GENERATED,
        correlation_id=getattr(request.state, "correlation_id", ""),
        payload={"symbol": symbol, **signal, "regime": regime},
    )
    stream_id = bus.publish("signal.generated", event)
    return {"symbol": symbol, "signal": signal, "stream_id": stream_id}
