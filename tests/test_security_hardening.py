from __future__ import annotations

import asyncio
from types import SimpleNamespace

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


class _CursorLoginUser:
    def execute(self, _query: str, _params=None) -> None:
        return None

    def fetchone(self):
        return (42, "hashed", "user", 1)


class _ConnLoginUser:
    def __init__(self) -> None:
        self.cursor_obj = _CursorLoginUser()
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cursor_obj

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


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
    monkeypatch.setattr(auth_routes.settings, "environment", "development")

    result = auth_routes.signup(
        auth_routes.SignupRequest(email="existing@example.com", password="StrongPass123"),
        _build_request("/auth/signup", "POST"),
    )

    assert result == {"status": "user created"}


def test_signup_blocked_when_public_signup_disabled(monkeypatch) -> None:
    monkeypatch.setattr(auth_routes.settings, "environment", "production")
    monkeypatch.setattr(auth_routes.settings, "allow_public_signup", False)

    try:
        auth_routes.signup(
            auth_routes.SignupRequest(email="new@example.com", password="StrongPass123"),
            _build_request("/auth/signup", "POST"),
        )
        raise AssertionError("Expected signup block when disabled")
    except HTTPException as exc:
        assert exc.status_code == 403
        assert "Public signup is disabled" in str(exc.detail)


def test_login_lockout_after_repeated_failures(monkeypatch) -> None:
    conn = _ConnLoginUser()
    monkeypatch.setattr(auth_routes, "get_connection", lambda: conn)
    monkeypatch.setattr(auth_routes, "release_connection", lambda _conn: None)
    monkeypatch.setattr(auth_routes, "verify_password", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(auth_routes.settings, "auth_lockout_threshold", 2)
    monkeypatch.setattr(auth_routes.settings, "auth_lockout_window_seconds", 300)
    monkeypatch.setattr(auth_routes.settings, "auth_lockout_duration_seconds", 60)

    auth_routes._FAILED_LOGIN_ATTEMPTS.clear()
    auth_routes._LOGIN_LOCKED_UNTIL.clear()

    req = auth_routes.LoginRequest(email="lock@example.com", password="WrongPass123")
    request = _build_request("/auth/login", "POST", "10.1.1.10")

    try:
        auth_routes.login(req, request)
        raise AssertionError("Expected first failure to be rejected")
    except HTTPException as exc:
        assert exc.status_code == 401

    try:
        auth_routes.login(req, request)
        raise AssertionError("Expected lockout on threshold breach")
    except HTTPException as exc:
        assert exc.status_code == 429

    auth_routes._FAILED_LOGIN_ATTEMPTS.clear()
    auth_routes._LOGIN_LOCKED_UNTIL.clear()


def test_google_route_absent_from_app() -> None:
    paths = {getattr(route, "path", "") for route in main.app.routes}
    assert "/auth/google" not in paths


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


def test_rate_limiter_applies_strict_limit_to_trading_paths() -> None:
    middleware = RateLimiterMiddleware(
        app=lambda *_args, **_kwargs: None,
        max_requests=60,
        auth_max_requests=12,
        critical_max_requests=2,
        window_seconds=60,
    )

    async def _call_next(_request: Request):
        return Response(status_code=200)

    req_trading = _build_request("/live-trading/enable", "POST")

    first = asyncio.run(middleware.dispatch(req_trading, _call_next))
    second = asyncio.run(middleware.dispatch(req_trading, _call_next))
    third = asyncio.run(middleware.dispatch(req_trading, _call_next))

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429


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


def test_validate_security_blocks_public_signup_in_production() -> None:
    settings = core_config.Settings(
        environment="production",
        trading_mode="paper",
        ws_allow_query_token=False,
        ws_require_origin_header=True,
        allow_public_signup=True,
        jwt_secret="x" * 40,
    )
    try:
        settings.validate_security()
        raise AssertionError("Expected RuntimeError for production public signup")
    except RuntimeError as exc:
        assert "ALLOW_PUBLIC_SIGNUP must be false in production" in str(exc)


def test_validate_security_blocks_insecure_cookie_override_in_production() -> None:
    settings = core_config.Settings(
        environment="production",
        trading_mode="paper",
        ws_allow_query_token=False,
        ws_require_origin_header=True,
        allow_public_signup=False,
        session_cookie_secure=False,
        jwt_secret="x" * 40,
    )
    try:
        settings.validate_security()
        raise AssertionError("Expected RuntimeError for insecure cookie override")
    except RuntimeError as exc:
        assert "SESSION_COOKIE_SECURE cannot be false in production" in str(exc)


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


class _CacheStub:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}
        self.locks: set[str] = set()
        self.force_lock_fail = False

    def get_json(self, key: str):
        return self.data.get(key)

    def set_json(self, key: str, value, ttl: int = 0) -> bool:
        self.data[key] = value
        return True

    def set_if_absent(self, key: str, _value: str, ttl: int = 0) -> bool:
        if self.force_lock_fail:
            return False
        if key in self.locks:
            return False
        self.locks.add(key)
        return True

    def delete(self, key: str) -> None:
        self.locks.discard(key)


class _FetcherStub:
    def fetch(self, _symbol: str):
        return {"close": [100.0]}


class _ColumnStub:
    def __init__(self, values):
        self.values = values

    @property
    def iloc(self):
        return self

    def __getitem__(self, idx: int):
        return self.values[idx]


class _FrameStub:
    empty = False

    def __init__(self, close: float):
        self._close = close

    def __getitem__(self, key: str):
        if key == "close":
            return _ColumnStub([self._close])
        raise KeyError(key)


class _FetcherFrameStub:
    def fetch(self, _symbol: str):
        return _FrameStub(100.0)


class _OrderManagerStub:
    def submit_market_order(self, symbol: str, side: str, quantity: float, price: float):
        return SimpleNamespace(
            status="filled",
            order_id=f"{symbol}-{side}-1",
            filled_price=price,
            error=None,
        )

    def cancel_all(self):
        return 3


class _PortfolioManagerStub:
    def __init__(self) -> None:
        self.closed: list[tuple[str, float]] = []

    def open_position(self, **_kwargs):
        return None

    def close_position(self, symbol: str, price: float):
        self.closed.append((symbol, price))

    def get_portfolio(self):
        return {
            "positions": {
                "BTCUSDT": {"quantity": 1.5, "side": "long"},
            }
        }


class _RiskManagerStub:
    def __init__(self) -> None:
        self.kill_activated = False
        self.kill_deactivated = False
        self.last_reason = ""

    def activate_kill_switch(self, reason: str = ""):
        self.kill_activated = True
        self.last_reason = reason

    def deactivate_kill_switch(self):
        self.kill_deactivated = True


def _build_api_request_with_services(services) -> Request:
    app = SimpleNamespace(state=SimpleNamespace(services=services))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [],
        "app": app,
    }
    return Request(scope)


def test_manual_buy_replays_cached_idempotent_result(monkeypatch) -> None:
    cache = _CacheStub()
    replay_key = "manual_trade:result:BTCUSDT:buy:key-12345678"
    cache.data[replay_key] = {"order_id": "cached-order"}

    services = SimpleNamespace(
        paper_trader=SimpleNamespace(execution=SimpleNamespace(order_manager=_OrderManagerStub())),
        cache=cache,
        fetcher=_FetcherFrameStub(),
        portfolio_manager=_PortfolioManagerStub(),
    )
    req = _build_api_request_with_services(services)
    body = main.ManualTradeRequest(
        symbol="BTCUSDT",
        side="buy",
        size_usd=250.0,
        idempotency_key="key-12345678",
    )

    monkeypatch.setattr(main, "_audit_action", lambda **_kwargs: None)

    result = asyncio.run(main.manual_buy(req, body, {"user_id": 1}))

    assert result["idempotent_replay"] is True
    assert result["order"]["order_id"] == "cached-order"


def test_manual_buy_rejects_when_symbol_lock_exists(monkeypatch) -> None:
    cache = _CacheStub()
    cache.force_lock_fail = True
    services = SimpleNamespace(
        paper_trader=SimpleNamespace(execution=SimpleNamespace(order_manager=_OrderManagerStub())),
        cache=cache,
        fetcher=_FetcherFrameStub(),
        portfolio_manager=_PortfolioManagerStub(),
    )
    req = _build_api_request_with_services(services)
    body = main.ManualTradeRequest(
        symbol="BTCUSDT",
        side="buy",
        size_usd=250.0,
        idempotency_key="key-87654321",
    )

    monkeypatch.setattr(main, "_audit_action", lambda **_kwargs: None)

    try:
        asyncio.run(main.manual_buy(req, body, {"user_id": 1}))
        raise AssertionError("Expected HTTPException for concurrent lock")
    except HTTPException as exc:
        assert exc.status_code == 409
        assert "Trade already in progress" in str(exc.detail)


def test_emergency_kill_and_reset_toggle_risk_manager(monkeypatch) -> None:
    risk = _RiskManagerStub()
    services = SimpleNamespace(
        risk_manager=risk,
        paper_trader=SimpleNamespace(execution=SimpleNamespace(order_manager=_OrderManagerStub())),
    )
    req = _build_api_request_with_services(services)

    monkeypatch.setattr(main, "_audit_action", lambda **_kwargs: None)

    kill_result = asyncio.run(main.emergency_kill(req, "incident_test", {"user_id": 9}))
    reset_result = asyncio.run(main.emergency_kill_reset(req, {"user_id": 9}))

    assert kill_result["status"] == "kill_switch_activated"
    assert kill_result["cancelled_orders"] == 3
    assert risk.kill_activated is True
    assert risk.last_reason == "incident_test"

    assert reset_result["status"] == "kill_switch_deactivated"
    assert risk.kill_deactivated is True
