"""Portfolio service maintaining positions, PnL and portfolio state snapshots."""

from __future__ import annotations

from fastapi import Request
from pydantic import BaseModel, Field

from backend.src.contracts.events import EventEnvelope, EventName
from backend.src.core.config import settings
from backend.src.core.event_stream import RedisStreamsBus
from backend.src.portfolio.portfolio_manager import PortfolioManager
from backend.src.services.shared.app_factory import create_service_app

app = create_service_app("portfolio-service")
bus = RedisStreamsBus(url=settings.redis_url, enabled=settings.redis_enabled)
portfolio = PortfolioManager(initial_cash=100000.0)


class PortfolioPriceUpdate(BaseModel):
    symbol: str
    price: float = Field(gt=0)
    correlation_id: str | None = None


@app.post("/portfolio/update")
async def update_portfolio(payload: PortfolioPriceUpdate, request: Request):
    portfolio.update_equity({payload.symbol: payload.price})
    perf = portfolio.get_performance()
    state = portfolio.get_portfolio()
    event = EventEnvelope(
        source="portfolio-service",
        event_name=EventName.PORTFOLIO_UPDATED,
        correlation_id=payload.correlation_id
        or getattr(request.state, "correlation_id", ""),
        payload={"performance": perf, "state": state},
    )
    stream_id = bus.publish("portfolio.updated", event)
    return {"performance": perf, "state": state, "stream_id": stream_id}


@app.get("/portfolio/status")
async def portfolio_status():
    return portfolio.get_portfolio()


@app.get("/portfolio/performance")
async def portfolio_performance():
    return portfolio.get_performance()


@app.get("/portfolio/state")
async def portfolio_state():
    return {
        "state": portfolio.get_portfolio(),
        "performance": portfolio.get_performance(),
    }
