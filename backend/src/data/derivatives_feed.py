"""
Derivatives data feed: funding rate, open interest, and liquidations
from Binance Futures API.

Uses the public REST endpoints (no API key required for market data).
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Lazy import — ccxt may not be installed
_CCXT_AVAILABLE = False
try:
    import ccxt
    _CCXT_AVAILABLE = True
except ImportError:
    logger.info("ccxt not available — derivatives feed disabled")

_REQUESTS_AVAILABLE = False
try:
    import requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    pass


class DerivativesFeed:
    """
    Fetch derivatives data (funding rate, open interest) from Binance.

    Supports:
      - Current and historical funding rates
      - Open interest snapshots
      - Long/short ratio from Binance Futures API
    """

    BINANCE_FAPI_BASE = "https://fapi.binance.com"

    def __init__(self):
        self._session = requests.Session() if _REQUESTS_AVAILABLE else None

    def get_funding_rate(
        self, symbol: str = "BTCUSDT", limit: int = 500
    ) -> pd.Series:
        """
        Fetch historical funding rates.

        Returns:
            pd.Series indexed by timestamp with funding rate values.
        """
        if not _REQUESTS_AVAILABLE:
            logger.warning("requests not available — returning empty funding rate")
            return pd.Series(dtype=float)

        try:
            url = f"{self.BINANCE_FAPI_BASE}/fapi/v1/fundingRate"
            params = {"symbol": symbol, "limit": limit}
            resp = self._session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            if not data:
                return pd.Series(dtype=float)

            df = pd.DataFrame(data)
            df["fundingTime"] = pd.to_datetime(df["fundingTime"], unit="ms")
            df["fundingRate"] = df["fundingRate"].astype(float)
            series = df.set_index("fundingTime")["fundingRate"]
            series = series.sort_index()
            return series

        except Exception as e:
            logger.error("Failed to fetch funding rate: %s", e)
            return pd.Series(dtype=float)

    def get_open_interest_hist(
        self, symbol: str = "BTCUSDT", period: str = "5m", limit: int = 500
    ) -> pd.Series:
        """
        Fetch historical open interest.

        Returns:
            pd.Series indexed by timestamp with OI values.
        """
        if not _REQUESTS_AVAILABLE:
            return pd.Series(dtype=float)

        try:
            url = f"{self.BINANCE_FAPI_BASE}/futures/data/openInterestHist"
            params = {"symbol": symbol, "period": period, "limit": limit}
            resp = self._session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            if not data:
                return pd.Series(dtype=float)

            df = pd.DataFrame(data)
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df["sumOpenInterest"] = df["sumOpenInterest"].astype(float)
            series = df.set_index("timestamp")["sumOpenInterest"]
            return series.sort_index()

        except Exception as e:
            logger.error("Failed to fetch open interest: %s", e)
            return pd.Series(dtype=float)

    def get_long_short_ratio(
        self, symbol: str = "BTCUSDT", period: str = "5m", limit: int = 500
    ) -> pd.DataFrame:
        """
        Fetch long/short account ratio.

        Returns:
            DataFrame with columns [longAccount, shortAccount, longShortRatio]
        """
        if not _REQUESTS_AVAILABLE:
            return pd.DataFrame()

        try:
            url = f"{self.BINANCE_FAPI_BASE}/futures/data/globalLongShortAccountRatio"
            params = {"symbol": symbol, "period": period, "limit": limit}
            resp = self._session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            if not data:
                return pd.DataFrame()

            df = pd.DataFrame(data)
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            for col in ["longAccount", "shortAccount", "longShortRatio"]:
                if col in df.columns:
                    df[col] = df[col].astype(float)
            return df.sort_index()

        except Exception as e:
            logger.error("Failed to fetch long/short ratio: %s", e)
            return pd.DataFrame()

    def get_current_funding(self, symbol: str = "BTCUSDT") -> Optional[float]:
        """Get the most recent funding rate."""
        series = self.get_funding_rate(symbol, limit=1)
        if len(series) > 0:
            return float(series.iloc[-1])
        return None

    def get_current_oi(self, symbol: str = "BTCUSDT") -> Optional[float]:
        """Get the most recent open interest value."""
        if not _REQUESTS_AVAILABLE:
            return None

        try:
            url = f"{self.BINANCE_FAPI_BASE}/fapi/v1/openInterest"
            params = {"symbol": symbol}
            resp = self._session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return float(data.get("openInterest", 0))

        except Exception as e:
            logger.error("Failed to fetch current OI: %s", e)
            return None
