"""
Application settings and configuration.

Loads from environment variables and .env file.
Uses pydantic-settings v2 with extra="ignore" so unknown env vars
never crash the server.
"""

from pathlib import Path
from typing import Optional

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
        extra="ignore",            # unknown env vars are silently ignored
        case_sensitive=False,       # PORT == port == Port
    )

    # --------------------------------------------------
    # Server
    # --------------------------------------------------
    port: int = 10000
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 10000           # kept for backwards compat

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
    # Data API keys
    # --------------------------------------------------
    cryptopanic_token: str = "demo"
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
    paper_trading_interval: int = 300       # seconds

    # --------------------------------------------------
    # Live trading (safety-critical)
    # --------------------------------------------------
    trading_mode: str = "paper"             # "paper" (default) or "live"
    live_trading_enabled: bool = False       # must be explicitly enabled
    live_max_position_usd: float = 100.0    # tiny default cap
    live_use_testnet: bool = True            # use Binance testnet by default
    require_api_key_validation: bool = True  # validate keys before trading


settings = Settings()
