"""Application settings and configuration."""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Data settings
    data_dir: Path = Path("data")
    default_symbol: str = "AAPL"
    default_period: str = "1y"

    # Model settings
    model_dir: Path = Path("models")
    test_size: float = 0.2
    random_state: int = 42

    # API settings
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Dashboard settings
    dashboard_port: int = 8501

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
