from __future__ import annotations

from urllib.parse import quote_plus, urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PlatformSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = Field(default="vision-ai")
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")

    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8080)

    redis_url: str = Field(default="redis://localhost:6379/0")
    queue_block_ms: int = Field(default=5000)

    database_url: SecretStr | None = Field(default=None, validation_alias="DATABASE_URL")
    db_host: str = Field(default="localhost", validation_alias="DB_HOST")
    db_port: int = Field(default=5432, validation_alias="DB_PORT")
    db_name: str = Field(default="vision_core", validation_alias="DB_NAME")
    db_user: str = Field(default="vision", validation_alias="DB_USER")
    db_password: SecretStr | None = Field(default=None, validation_alias="DB_PASSWORD")

    default_symbol: str = Field(default="BTCUSDT")
    artifacts_dir: str = Field(default="data")
    max_position_size: float = Field(default=1.0, ge=0.0)
    max_notional_exposure: float = Field(default=50000.0, ge=0.0)
    max_drawdown_pct: float = Field(default=0.15, ge=0.0, le=1.0)

    trading_poll_seconds: float = Field(default=1.0)
    execution_retry_limit: int = Field(default=3)
    execution_retry_delay_seconds: float = Field(default=0.75)
    force_test_trade: bool = Field(default=False)
    force_test_trade_notional: float = Field(default=25.0, gt=0.0)
    force_test_trade_every_n_ticks: int = Field(default=50, ge=1)
    market_tick_publish_interval_ms: int = Field(default=1000, ge=100)

    @model_validator(mode="after")
    def _validate_db_configuration(self) -> "PlatformSettings":
        if self.database_url is not None:
            return self

        if self.db_password is None or not self.db_password.get_secret_value().strip():
            raise ValueError(
                "Missing database configuration: set DATABASE_URL or set DB_PASSWORD together with DB_HOST/DB_PORT/DB_NAME/DB_USER"
            )
        return self

    @property
    def database_url_value(self) -> str:
        if self.database_url is not None:
            return self.database_url.get_secret_value()
        password = quote_plus(self.db_password.get_secret_value() if self.db_password is not None else "")
        user = quote_plus(self.db_user)
        return f"postgresql://{user}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"

    def validate_startup(self) -> None:
        issues: list[str] = []
        if self.api_port <= 0:
            issues.append("API_PORT must be a positive integer")
        if not self.redis_url.strip():
            issues.append("REDIS_URL must be set")
        if not self.database_url_value.strip():
            issues.append("DATABASE_URL or DB_* variables must resolve to a database connection string")
        if self.force_test_trade and self.force_test_trade_notional <= 0:
            issues.append("FORCE_TEST_TRADE_NOTIONAL must be positive when FORCE_TEST_TRADE is enabled")
        if self.force_test_trade_every_n_ticks <= 0:
            issues.append("FORCE_TEST_TRADE_EVERY_N_TICKS must be >= 1")
        if str(self.environment).lower() == "production":
            if "localhost" in self.redis_url or "127.0.0.1" in self.redis_url:
                issues.append("REDIS_URL must use a service hostname in production, not localhost")
            if str(self.db_host).lower() in {"localhost", "127.0.0.1"} and self.database_url is None:
                issues.append("DB_HOST must not be localhost in production when using DB_* settings")
            if self.database_url is not None:
                db_host = str(urlparse(self.database_url.get_secret_value()).hostname or "").lower()
                if db_host in {"localhost", "127.0.0.1"}:
                    issues.append("DB_HOST must not be localhost in production when using DB_* settings")
            if self.force_test_trade:
                issues.append("FORCE_TEST_TRADE must be disabled in production")
        if issues:
            raise ValueError("; ".join(issues))

    @staticmethod
    def _mask_redis_url(url: str) -> str:
        parsed = urlparse(url)
        if not parsed.scheme:
            return "<invalid_redis_url>"
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        db = parsed.path or ""
        if parsed.username or parsed.password:
            return f"{parsed.scheme}://<redacted>@{host}{port}{db}"
        return f"{parsed.scheme}://{host}{port}{db}"

    def startup_diagnostics(self) -> dict[str, str | int]:
        return {
            "service_name": self.service_name,
            "environment": self.environment,
            "api_host": self.api_host,
            "api_port": self.api_port,
            "redis_url": self._mask_redis_url(self.redis_url),
            "db_host": self.db_host,
            "db_port": self.db_port,
            "db_name": self.db_name,
            "db_user": self.db_user,
            "database_url_source": "DATABASE_URL" if self.database_url is not None else "DB_COMPONENTS",
        }


settings = PlatformSettings()
