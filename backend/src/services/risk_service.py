"""Risk service performing pre-trade risk checks and publishing decisions."""

from __future__ import annotations

from fastapi import Request

from backend.src.contracts.events import (EventEnvelope, EventName,
                                          RiskCheckRequest)
from backend.src.core.config import settings
from backend.src.core.event_stream import RedisStreamsBus
from backend.src.data.fetcher import DataFetcher
from backend.src.features.indicators import FeatureEngineer
from backend.src.risk.risk_manager import RiskManager
from backend.src.risk.risk_score import RiskScore
from backend.src.services.shared.app_factory import create_service_app

app = create_service_app("risk-service")
bus = RedisStreamsBus(url=settings.redis_url, enabled=settings.redis_enabled)
risk_manager = RiskManager()
risk_score = RiskScore()
fetcher = DataFetcher()
engineer = FeatureEngineer()


@app.get("/risk/status")
async def risk_status(symbol: str = "BTC/USDT"):
    clean_symbol = symbol.replace("/", "").replace("USDT", "/USDT")
    try:
        df = fetcher.fetch(clean_symbol)
        df = engineer.add_all_indicators(df)
        risk = risk_score.calculate_risk(df)
    except Exception:
        risk = {
            "risk_level": "medium",
            "risk_score": 0.5,
            "factors": {"error": "fetch_failed"},
        }

    risk["kill_switch"] = risk_manager.kill_switch_active
    risk["events"] = risk_manager.get_events(limit=10)
    return risk


@app.post("/risk/check")
async def risk_check(payload: RiskCheckRequest, request: Request):
    portfolio = {
        "cash": payload.quantity * payload.price * 10,
        "equity_curve": [payload.quantity * payload.price * 10],
        "open_trades": 0,
        "positions": {},
        "daily_pnl": 0,
    }
    trade_value = payload.quantity * payload.price
    decision = risk_manager.approve_trade(portfolio, trade_value, payload.volatility)
    event = EventEnvelope(
        source="risk-service",
        event_name=EventName.RISK_DECISION,
        correlation_id=payload.correlation_id
        or getattr(request.state, "correlation_id", ""),
        payload={
            "symbol": payload.symbol,
            "decision": decision,
            "trade_value": trade_value,
        },
    )
    stream_id = bus.publish("risk.decision", event)
    return {"decision": decision, "stream_id": stream_id}
