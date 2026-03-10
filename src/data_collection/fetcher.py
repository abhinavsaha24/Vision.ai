import ccxt
import pandas as pd
import time


class DataFetcher:

    def __init__(self):

        self.exchange = ccxt.binance({
            "enableRateLimit": True,
            "options": {
                "defaultType": "spot"
            }
        })


    def fetch(self, symbol="BTC/USDT", timeframe="5m", limit=500):

        """
        Fetch OHLCV data from Binance and return a cleaned pandas DataFrame.
        """

        try:

            # Fetch raw data
            ohlcv = self.exchange.fetch_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                limit=limit
            )

            if not ohlcv:
                raise ValueError("No data returned from exchange")

            # Convert to dataframe
            df = pd.DataFrame(
                ohlcv,
                columns=[
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume"
                ]
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

            return df

        except ccxt.NetworkError as e:
            print("Network error while fetching data:", e)
            time.sleep(2)
            return self.fetch(symbol, timeframe, limit)

        except ccxt.ExchangeError as e:
            print("Exchange error:", e)
            raise

        except Exception as e:
            print("Data fetch failed:", e)
            raise