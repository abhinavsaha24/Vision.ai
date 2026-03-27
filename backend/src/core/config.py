"""
Application settings and configuration.

Loads from environment variables and .env file.
Uses pydantic-settings v2 with extra="ignore" so unknown env vars
never crash the server.
"""

import secrets
from pathlib import Path
from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central configuration for the Vision AI trading platform.

    All fields map to environment variables (case-insensitive).
    Defaults are safe for paper-trading / development.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # unknown env vars are silently ignored
        case_sensitive=False,  # PORT == port == Port
    )

    # --------------------------------------------------
    # Server
    # --------------------------------------------------
    environment: str = "production"
    port: int = 8080
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8080  # kept for backwards compat

    # --------------------------------------------------
    # Data
    # --------------------------------------------------
    data_dir: Path = Path("data")
    default_symbol: str = "BTC/USDT"
    default_period: str = "1y"
    default_timeframe: str = "5m"

    # --------------------------------------------------
    # ML / Models
    # --------------------------------------------------
    model_dir: Path = Path("models")
    test_size: float = 0.2
    random_state: int = 42
    model_name: str = "trading_model"
    hf_token: Optional[str] = None

    # --------------------------------------------------
    # Exchange
    # --------------------------------------------------
    binance_api_key: Optional[str] = None
    binance_secret: Optional[str] = None

    # --------------------------------------------------
    # Security
    # --------------------------------------------------
    # Accept both JWT_SECRET and legacy VISION_AI_SECRET env var names.
    # In paper mode, a secure ephemeral fallback is generated when missing.
    jwt_secret: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("JWT_SECRET", "VISION_AI_SECRET", "jwt_secret"),
    )
    session_cookie_name: str = "vision_ai_token"
    csrf_cookie_name: str = "vision_ai_csrf"
    csrf_header_name: str = "X-CSRF-Token"
    session_cookie_max_age_seconds: int = 60 * 60 * 24 * 7
    session_cookie_secure: Optional[bool] = None
    allow_public_signup: bool = False
    auth_lockout_threshold: int = 5
    auth_lockout_window_seconds: int = 300
    auth_lockout_duration_seconds: int = 900
    mfa_step_up_enabled: bool = False
    mfa_totp_secret: Optional[str] = None
    mfa_step_up_window: int = 1

    # --------------------------------------------------
    # Data API keys
    # --------------------------------------------------
    cryptopanic_token: Optional[str] = None
    newsapi_key: Optional[str] = None
    finnhub_key: Optional[str] = None

    # --------------------------------------------------
    # Dashboard
    # --------------------------------------------------
    dashboard_port: int = 8501

    # --------------------------------------------------
    # Redis Cache
    # --------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"
    redis_ttl: int = 30
    redis_enabled: bool = False

    # --------------------------------------------------
    # Internal service routing (Phase 0 strangler)
    # --------------------------------------------------
    risk_service_url: Optional[str] = None
    portfolio_service_url: Optional[str] = None
    internal_service_delegation_enabled: bool = True
    internal_service_timeout_seconds: float = 2.0
    internal_service_failure_cooldown_seconds: float = 30.0
    internal_service_failure_cooldown_max_seconds: float = 300.0
    internal_service_fail_fast_local_hosts: bool = True

    # --------------------------------------------------
    # CORS
    # --------------------------------------------------
    cors_allowed_origins: str = (
        "http://localhost:3000,"
        "http://127.0.0.1:3000,"
        "http://localhost:3001,"
        "http://127.0.0.1:3001"
    )
    cors_allow_origin_regex: Optional[str] = r"https://.*\.vercel\.app"
    cors_allow_methods: str = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
    cors_allow_headers: str = "Authorization,Content-Type,X-Request-ID,X-Correlation-ID,X-CSRF-Token"

    # --------------------------------------------------
    # Risk
    # --------------------------------------------------
    max_position_size: float = 0.05
    max_daily_loss: float = 0.05
    max_drawdown: float = 0.20
    max_open_trades: int = 5

    # --------------------------------------------------
    # Paper trading
    # --------------------------------------------------
    paper_trading_initial_cash: float = 10000
    paper_trading_interval: int = 300  # seconds
    paper_trading_api_autostart: bool = False
    enable_openapi_docs: bool = False

    # --------------------------------------------------
    # Realtime feed resilience
    # --------------------------------------------------
    realtime_ws_enabled: bool = True
    realtime_ws_open_timeout_seconds: float = 12.0
    realtime_ws_max_consecutive_failures: int = 5
    realtime_ws_cooldown_seconds: float = 90.0
    realtime_rest_poll_seconds: float = 6.0
    ws_allow_query_token: bool = False
    ws_require_origin_header: bool = False

    # --------------------------------------------------
    # Live trading (safety-critical)
    # --------------------------------------------------
    trading_mode: str = "paper"  # "paper" (default) or "live"
    live_trading_enabled: bool = False  # must be explicitly enabled
    live_max_position_usd: float = 100.0  # tiny default cap
    live_use_testnet: bool = True  # use Binance testnet by default
    require_api_key_validation: bool = True  # validate keys before trading

    def validate_security(self) -> None:
        """Validate required security controls."""
        jwt_value = (self.jwt_secret or "").strip()
        env_name = str(self.environment or "").strip().lower()
        mode = str(self.trading_mode or "").strip().lower()

        if int(self.auth_lockout_threshold) < 1:
            raise RuntimeError("AUTH_LOCKOUT_THRESHOLD must be >= 1.")
        if int(self.auth_lockout_window_seconds) < 1:
            raise RuntimeError("AUTH_LOCKOUT_WINDOW_SECONDS must be >= 1.")
        if int(self.auth_lockout_duration_seconds) < 1:
            raise RuntimeError("AUTH_LOCKOUT_DURATION_SECONDS must be >= 1.")

        if self.mfa_step_up_enabled and not (self.mfa_totp_secret or "").strip():
            raise RuntimeError(
                "MFA_STEP_UP_ENABLED is true but MFA_TOTP_SECRET is not configured."
            )

        if env_name == "production" and bool(self.ws_allow_query_token):
            raise RuntimeError(
                "WS_ALLOW_QUERY_TOKEN must be false in production. "
                "Use Authorization/cookie/subprotocol websocket auth instead."
            )

        if env_name == "production" and bool(self.allow_public_signup):
            raise RuntimeError(
                "ALLOW_PUBLIC_SIGNUP must be false in production. "
                "Use invite/admin-provisioned accounts."
            )

        if env_name == "production" and self.session_cookie_secure is False:
            raise RuntimeError(
                "SESSION_COOKIE_SECURE cannot be false in production."
            )

        if mode == "live" and not bool(self.ws_require_origin_header):
            raise RuntimeError(
                "WS_REQUIRE_ORIGIN_HEADER must be true when trading_mode=live."
            )

        if mode == "live":
            if not self.binance_api_key or not self.binance_secret:
                raise RuntimeError(
                    "Live trading mode requires BINANCE_API_KEY and BINANCE_SECRET."
                )

            if len(jwt_value) < 32:
                raise RuntimeError(
                    "JWT_SECRET must be at least 32 characters and provided via environment for live trading."
                )
            return

        # Paper mode fallback: keep the API bootable on ephemeral environments.
        if len(jwt_value) < 32:
            self.jwt_secret = secrets.token_urlsafe(48)


settings = Settings()
