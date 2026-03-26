"""
Market data fetcher with Redis caching and retry logic.

Features:
  - Binance OHLCV via CCXT
  - Optional Redis cache with configurable TTL
  - Retry on network errors
  - Always returns a valid DataFrame (empty on failure)
"""

import json
import logging
import time

import ccxt
import pandas as pd

logger = logging.getLogger(__name__)

# Optional Redis cache
_cache = None
try:
    from backend.src.core.config import settings

    if settings.redis_enabled:
        from backend.src.core.cache import RedisCache

        _cache = RedisCache(
            url=settings.redis_url,
            default_ttl=settings.redis_ttl,
            enabled=True,
        )
except Exception as e:
    logger.info("Redis cache not initialized for DataFetcher: %s", e)


class DataFetcher:

    def __init__(self):
        self.exchange = ccxt.binanceus(
            {"enableRateLimit": True, "options": {"defaultType": "spot"}}
        )

    def fetch(self, symbol="BTC/USDT", timeframe="5m", limit=500):
        """
        Fetch OHLCV data from Binance and return a cleaned pandas DataFrame.
        Uses Redis cache when available to reduce API calls.
        """
        # Check cache first
        cache_key = f"ohlcv:{symbol}:{timeframe}:{limit}"
        if _cache and _cache.connected:
            cached = _cache.get(cache_key)
            if cached:
                try:
                    data = json.loads(cached)
                    df = pd.DataFrame(data)
                    df["timestamp"] = pd.to_datetime(df["timestamp"])
                    df.set_index("timestamp", inplace=True)
                    logger.debug("Cache hit: %s", cache_key)
                    return df
                except Exception:
                    pass  # cache miss / corrupt data

        try:
            # Fetch raw data
            ohlcv = self.exchange.fetch_ohlcv(
                symbol=symbol, timeframe=timeframe, limit=limit
            )

            if not ohlcv:
                raise ValueError("No data returned from exchange")

            # Convert to dataframe
            df = pd.DataFrame(
                ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

            # Convert timestamp
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

            # Set index
            df.set_index("timestamp", inplace=True)

            # Ensure numeric types
            df = df.astype(float)

            # Sort data
            df = df.sort_index()

            # Remove duplicates
            df = df[~df.index.duplicated(keep="last")]

            # Forward fill small gaps
            df = df.ffill()

            # Cache the result
            if _cache and _cache.connected:
                try:
                    cache_data = df.reset_index().to_json(
                        orient="records", date_format="iso"
                    )
                    _cache.set(cache_key, cache_data)
                except Exception as e:
                    logger.debug("Cache store failed: %s", e)

            return df

        except ccxt.NetworkError as e:
            logger.warning("Network error while fetching data: %s", e)
            time.sleep(2)
            try:
                # One retry
                ohlcv = self.exchange.fetch_ohlcv(
                    symbol=symbol, timeframe=timeframe, limit=limit
                )
                df = pd.DataFrame(
                    ohlcv,
                    columns=["timestamp", "open", "high", "low", "close", "volume"],
                )
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                df.set_index("timestamp", inplace=True)
                df = df.astype(float).sort_index()
                return df[~df.index.duplicated(keep="last")].ffill()
            except Exception as retry_err:
                logger.error("Retry fetch failed: %s", retry_err)
                return pd.DataFrame()

        except ccxt.ExchangeError as e:
            logger.error("Exchange error: %s", e)
            return pd.DataFrame()

        except Exception as e:
            logger.error("Data fetch failed: %s", e)
            return pd.DataFrame()
