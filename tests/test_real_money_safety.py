from backend.src.core.config import Settings


def test_production_forbids_ws_query_token() -> None:
    s = Settings(
        environment="production",
        ws_allow_query_token=True,
        allow_public_signup=False,
        session_cookie_secure=True,
        auth_lockout_threshold=5,
        auth_lockout_window_seconds=300,
        auth_lockout_duration_seconds=900,
        jwt_secret="x" * 40,
    )
    try:
        s.validate_security()
        raise AssertionError("Expected production websocket query token rejection")
    except RuntimeError as exc:
        assert "WS_ALLOW_QUERY_TOKEN" in str(exc)


def test_live_mode_requires_origin_header_enforcement() -> None:
    s = Settings(
        environment="production",
        trading_mode="live",
        ws_require_origin_header=False,
        allow_public_signup=False,
        session_cookie_secure=True,
        binance_api_key="k",
        binance_secret="s",
        jwt_secret="x" * 40,
        auth_lockout_threshold=5,
        auth_lockout_window_seconds=300,
        auth_lockout_duration_seconds=900,
    )
    try:
        s.validate_security()
        raise AssertionError("Expected live mode origin header rejection")
    except RuntimeError as exc:
        assert "WS_REQUIRE_ORIGIN_HEADER" in str(exc)


def test_live_mode_requires_exchange_keys() -> None:
    s = Settings(
        environment="production",
        trading_mode="live",
        ws_require_origin_header=True,
        allow_public_signup=False,
        session_cookie_secure=True,
        binance_api_key="",
        binance_secret="",
        jwt_secret="x" * 40,
        auth_lockout_threshold=5,
        auth_lockout_window_seconds=300,
        auth_lockout_duration_seconds=900,
    )
    try:
        s.validate_security()
        raise AssertionError("Expected missing exchange keys rejection")
    except RuntimeError as exc:
        assert "BINANCE_API_KEY" in str(exc)


def test_paper_mode_generates_fallback_secret() -> None:
    s = Settings(
        environment="development",
        trading_mode="paper",
        jwt_secret="short",
        auth_lockout_threshold=5,
        auth_lockout_window_seconds=300,
        auth_lockout_duration_seconds=900,
    )
    s.validate_security()
    assert s.jwt_secret is not None
    assert len(s.jwt_secret) >= 32
