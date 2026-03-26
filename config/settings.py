"""Application settings and configuration."""

from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"  # Ignore extra environment variables
    )

    # Data settings
    data_dir: Path = Path("data")
    default_symbol: str = "BTC/USDT"
    default_period: str = "1y"
    default_timeframe: str = "5m"

    # Model settings
    model_dir: Path = Path("models")
    test_size: float = 0.2
    random_state: int = 42
    model_name: str = "trading_model"

    # API settings
    api_host: str = "0.0.0.0"
    api_port: int = 10000

    # Dashboard settings
    dashboard_port: int = 8501

    # Exchange settings
    binance_api_key: Optional[str] = None
    binance_secret: Optional[str] = None

    # Database & Cache
    database_url: Optional[str] = None
    redis_url: Optional[str] = None

    # Security
    jwt_secret: Optional[str] = None

    # Sentiment API keys
    cryptopanic_token: str = "demo"
    newsapi_key: Optional[str] = None
    finnhub_key: Optional[str] = None
    hf_token: Optional[str] = None

    # Risk settings
    max_position_size: float = 0.05
    max_daily_loss: float = 0.05
    max_drawdown: float = 0.20
    max_open_trades: int = 5

    # Paper trading
    paper_trading_initial_cash: float = 10000
    paper_trading_interval: int = 300  # seconds

    # --------------------------------------------------
    # Live trading settings (safety-critical)
    # --------------------------------------------------
    trading_mode: str = "paper"              # "paper" (default) or "live"
    live_trading_enabled: bool = False        # must be explicitly enabled
    live_max_position_usd: float = 100.0     # tiny default cap
    live_use_testnet: bool = True             # use Binance testnet by default
    require_api_key_validation: bool = True   # validate keys before trading

    # Microservices
    risk_service_url: Optional[str] = None
    portfolio_service_url: Optional[str] = None

    # Frontend
    next_public_api_url: Optional[str] = None

    # Logging
    port: int = 10000
    log_level: str = "INFO"


settings = Settings()
