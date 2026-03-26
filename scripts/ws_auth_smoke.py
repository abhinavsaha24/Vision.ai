from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone

import jwt
import requests
import websockets


def _wait_for_health(api_url: str, timeout_seconds: int = 60) -> None:
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        try:
            response = requests.get(f"{api_url.rstrip('/')}/health", timeout=5)
            if response.status_code < 500:
                return
            last_error = f"health status {response.status_code}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1)
    raise RuntimeError(f"API did not become healthy in time: {last_error}")


def _build_token(secret: str) -> str:
    payload = {
        "user_id": 1,
        "role": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


async def _expect_rejection(url: str, *, origin: str | None, subprotocols: list[str] | None, expected_close_codes: set[int]) -> None:
    try:
        async with websockets.connect(
            url,
            origin=origin,
            subprotocols=subprotocols,
            open_timeout=8,
            close_timeout=3,
        ) as ws:
            try:
                await asyncio.wait_for(ws.recv(), timeout=4)
                raise RuntimeError("Expected websocket rejection, but received data")
            except websockets.exceptions.ConnectionClosed as exc:
                if exc.code not in expected_close_codes:
                    raise RuntimeError(
                        f"Unexpected close code {exc.code}; expected one of {sorted(expected_close_codes)}"
                    )
    except websockets.exceptions.InvalidStatus as exc:
        status_code = int(getattr(getattr(exc, "response", None), "status_code", 0) or 0)
        if status_code not in {400, 401, 403}:
            raise RuntimeError(f"Unexpected HTTP handshake status {status_code}")
    except websockets.exceptions.InvalidStatusCode as exc:
        if exc.status_code not in {400, 401, 403}:
            raise RuntimeError(f"Unexpected HTTP handshake status {exc.status_code}")


async def _expect_success(url: str, *, origin: str, token: str) -> None:
    async with websockets.connect(
        url,
        origin=origin,
        subprotocols=["vision-ai.v1", f"bearer.{token}"],
        open_timeout=8,
        close_timeout=3,
    ) as ws:
        raw = await asyncio.wait_for(ws.recv(), timeout=8)
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise RuntimeError("Websocket success check returned non-object payload")


async def _run_checks(api_url: str, token: str) -> None:
    ws_base = api_url.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
    market_ws = f"{ws_base}/ws/market?symbol=BTCUSDT"

    await _expect_rejection(
        market_ws,
        origin=None,
        subprotocols=["vision-ai.v1", f"bearer.{token}"],
        expected_close_codes={4003},
    )

    await _expect_rejection(
        f"{market_ws}&token={token}",
        origin="https://visiontrading.vercel.app",
        subprotocols=["vision-ai.v1"],
        expected_close_codes={4001},
    )

    await _expect_success(
        market_ws,
        origin="https://visiontrading.vercel.app",
        token=token,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Websocket auth hardening smoke checks")
    parser.add_argument("--api-url", default=os.getenv("WS_SMOKE_API_URL", "http://127.0.0.1:8090"))
    args = parser.parse_args()

    secret = (os.getenv("JWT_SECRET") or "").strip()
    if len(secret) < 32:
        raise RuntimeError("JWT_SECRET must be set to at least 32 chars for ws smoke checks")

    _wait_for_health(args.api_url)
    token = _build_token(secret)
    asyncio.run(_run_checks(args.api_url, token))
    print("ws_auth_smoke: ok")


if __name__ == "__main__":
    main()
