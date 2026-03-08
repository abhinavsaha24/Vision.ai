import ccxt
import pandas as pd


class DataFetcher:

    def __init__(self):
        self.exchange = ccxt.binance()

    def fetch(self, symbol="BTC/USDT", timeframe="5m", limit=500):

        ohlcv = self.exchange.fetch_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            limit=limit
        )

        df = pd.DataFrame(
            ohlcv,
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )

        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)

        return df