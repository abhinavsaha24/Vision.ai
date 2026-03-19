"""Factory for uniform service applications with health, readiness and tracing."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID", uuid4().hex[:16])
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response


def create_service_app(
    service_name: str, version: str = "1.0.0", description: Optional[str] = None
) -> FastAPI:
    app = FastAPI(
        title=service_name, version=version, description=description or service_name
    )
    app.add_middleware(CorrelationMiddleware)

    @app.get("/health/live")
    async def health_live():
        return {"status": "alive", "service": service_name}

    @app.get("/health/ready")
    async def health_ready():
        return {
            "status": "ready",
            "service": service_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.exception_handler(Exception)
    async def on_error(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={
                "error": "service_error",
                "service": service_name,
                "detail": str(exc),
                "correlation_id": getattr(request.state, "correlation_id", ""),
            },
        )

    return app
