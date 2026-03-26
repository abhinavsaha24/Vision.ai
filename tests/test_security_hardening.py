from __future__ import annotations

import asyncio

from fastapi import HTTPException
from fastapi.responses import Response
from starlette.requests import Request

from backend.src.api import auth_routes, main
from backend.src.core import config as core_config
from backend.src.core.rate_limiter import RateLimiterMiddleware


class _CursorExistingUser:
    def __init__(self) -> None:
        self._fetched = False

    def execute(self, _query: str, _params=None) -> None:
        return None

    def fetchone(self):
        if not self._fetched:
            self._fetched = True
            return (123,)
        return None


class _ConnExistingUser:
    def __init__(self) -> None:
        self.cursor_obj = _CursorExistingUser()
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self) -> None:
        self.committed = True


class _WebSocketStub:
    def __init__(self, headers=None, cookies=None, query_params=None) -> None:
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.query_params = query_params or {}
        self.closed_code: int | None = None
        self.closed_reason: str | None = None

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed_code = code
        self.closed_reason = reason


def _build_request(path: str, method: str = "GET", client_ip: str = "127.0.0.1") -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "client": (client_ip, 50000),
        "scheme": "http",
        "query_string": b"",
        "server": ("testserver", 80),
    }
    return Request(scope)


def test_password_strength_rejects_short_password() -> None:
    try:
        auth_routes._validate_password_strength("Abc123")
        raise AssertionError("Expected HTTPException for short password")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "at least 10 characters" in str(exc.detail)


def test_password_strength_requires_letter_and_number() -> None:
    try:
        auth_routes._validate_password_strength("abcdefghij")
        raise AssertionError("Expected HTTPException for missing number")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "one letter and one number" in str(exc.detail)


def test_password_strength_accepts_valid_password() -> None:
    auth_routes._validate_password_strength("StrongPass123")


def test_signup_existing_user_returns_generic_success(monkeypatch) -> None:
    conn = _ConnExistingUser()

    monkeypatch.setattr(auth_routes, "get_connection", lambda: conn)
    monkeypatch.setattr(auth_routes, "release_connection", lambda _conn: None)

    result = auth_routes.signup(
        auth_routes.SignupRequest(email="existing@example.com", password="StrongPass123")
    )

    assert result == {"status": "user created"}
    assert conn.committed is False


def test_extract_ws_token_precedence_header_over_all_sources() -> None:
    websocket = _WebSocketStub(
        headers={
            "authorization": "Bearer header-token",
            "sec-websocket-protocol": "vision-ai.v1,bearer.protocol-token",
        },
        cookies={"vision_ai_token": "cookie-token"},
        query_params={"token": "query-token"},
    )

    token = main._extract_ws_token(websocket)
    assert token == "header-token"


def test_extract_ws_token_uses_subprotocol_then_cookie() -> None:
    websocket_protocol = _WebSocketStub(
        headers={"sec-websocket-protocol": "vision-ai.v1,bearer.protocol-token"}
    )
    assert main._extract_ws_token(websocket_protocol) == "protocol-token"

    websocket_cookie = _WebSocketStub(cookies={"vision_ai_token": "cookie-token"})
    assert main._extract_ws_token(websocket_cookie) == "cookie-token"


def test_extract_ws_token_query_fallback_respects_setting(monkeypatch) -> None:
    websocket = _WebSocketStub(query_params={"token": "query-token"})

    monkeypatch.setattr(main.settings, "ws_allow_query_token", False)
    assert main._extract_ws_token(websocket) is None

    monkeypatch.setattr(main.settings, "ws_allow_query_token", True)
    assert main._extract_ws_token(websocket) == "query-token"


def test_select_ws_subprotocol_prefers_supported_protocol() -> None:
    websocket = _WebSocketStub(
        headers={"sec-websocket-protocol": "bearer.xyz, vision-ai.v1"}
    )
    assert main._select_ws_subprotocol(websocket) == "vision-ai.v1"


def test_select_ws_subprotocol_returns_none_when_missing() -> None:
    websocket = _WebSocketStub(headers={"sec-websocket-protocol": "bearer.xyz"})
    assert main._select_ws_subprotocol(websocket) is None


def test_rate_limiter_applies_stricter_auth_limit() -> None:
    middleware = RateLimiterMiddleware(
        app=lambda *_args, **_kwargs: None,
        max_requests=5,
        auth_max_requests=2,
        window_seconds=60,
    )

    async def _call_next(_request: Request):
        return Response(status_code=200)

    req_auth = _build_request("/auth/login", "POST")

    first = asyncio.run(middleware.dispatch(req_auth, _call_next))
    second = asyncio.run(middleware.dispatch(req_auth, _call_next))
    third = asyncio.run(middleware.dispatch(req_auth, _call_next))

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429


def test_rate_limiter_keeps_higher_limit_non_auth_paths() -> None:
    middleware = RateLimiterMiddleware(
        app=lambda *_args, **_kwargs: None,
        max_requests=3,
        auth_max_requests=1,
        window_seconds=60,
    )

    async def _call_next(_request: Request):
        return Response(status_code=200)

    req_api = _build_request("/portfolio/status", "GET")

    first = asyncio.run(middleware.dispatch(req_api, _call_next))
    second = asyncio.run(middleware.dispatch(req_api, _call_next))
    third = asyncio.run(middleware.dispatch(req_api, _call_next))
    fourth = asyncio.run(middleware.dispatch(req_api, _call_next))

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 200
    assert fourth.status_code == 429


def test_stream_channel_rejects_missing_origin_when_required(monkeypatch) -> None:
    websocket = _WebSocketStub(headers={}, query_params={"token": "ignored"})
    monkeypatch.setattr(main.settings, "ws_require_origin_header", True)

    async def _payload_builder(*_args, **_kwargs):
        return {}

    asyncio.run(
        main._stream_channel(
            websocket=websocket,
            channel="market",
            symbol="BTCUSDT",
            interval_seconds=1.0,
            payload_builder=_payload_builder,
        )
    )

    assert websocket.closed_code == 4003
    assert websocket.closed_reason == "Origin not allowed"


def test_stream_channel_rejects_invalid_token(monkeypatch) -> None:
    websocket = _WebSocketStub(
        headers={"origin": "http://localhost:3000"},
        query_params={},
    )
    monkeypatch.setattr(main.settings, "ws_require_origin_header", False)

    async def _payload_builder(*_args, **_kwargs):
        return {}

    asyncio.run(
        main._stream_channel(
            websocket=websocket,
            channel="market",
            symbol="BTCUSDT",
            interval_seconds=1.0,
            payload_builder=_payload_builder,
        )
    )

    assert websocket.closed_code == 4001
    assert websocket.closed_reason == "Authentication required"


def test_validate_security_blocks_query_token_fallback_in_production() -> None:
    settings = core_config.Settings(
        environment="production",
        trading_mode="paper",
        ws_allow_query_token=True,
        ws_require_origin_header=True,
        jwt_secret="x" * 40,
    )
    try:
        settings.validate_security()
        raise AssertionError("Expected RuntimeError for production query-token fallback")
    except RuntimeError as exc:
        assert "WS_ALLOW_QUERY_TOKEN must be false in production" in str(exc)


def test_validate_security_blocks_live_without_origin_enforcement() -> None:
    settings = core_config.Settings(
        environment="staging",
        trading_mode="live",
        ws_allow_query_token=False,
        ws_require_origin_header=False,
        jwt_secret="x" * 40,
        binance_api_key="key",
        binance_secret="secret",
    )
    try:
        settings.validate_security()
        raise AssertionError("Expected RuntimeError for live mode origin requirement")
    except RuntimeError as exc:
        assert "WS_REQUIRE_ORIGIN_HEADER must be true" in str(exc)


def test_validate_security_accepts_secure_live_configuration() -> None:
    settings = core_config.Settings(
        environment="production",
        trading_mode="live",
        ws_allow_query_token=False,
        ws_require_origin_header=True,
        jwt_secret="x" * 40,
        binance_api_key="key",
        binance_secret="secret",
    )
    settings.validate_security()
