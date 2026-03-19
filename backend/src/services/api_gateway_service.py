"""API gateway facade exposing service topology and routing metadata."""

from __future__ import annotations

from backend.src.services.shared.app_factory import create_service_app

app = create_service_app("api-gateway")


@app.get("/topology")
async def topology():
    return {
        "services": [
            "market-data-service",
            "feature-service",
            "model-service",
            "signal-service",
            "strategy-service",
            "risk-service",
            "portfolio-service",
            "execution-gateway",
            "order-state-service",
            "api-gateway",
        ]
    }
