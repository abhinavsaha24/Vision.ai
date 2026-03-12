import numpy as np


class MarketRegimeDetector:

    def detect_volatility(self, df):

        volatility = df["Returns"].rolling(20).std().iloc[-1]

        avg_vol = df["Returns"].rolling(20).std().mean()

        if volatility > avg_vol:
            return "high_volatility"

        return "low_volatility"


    def detect_trend(self, df):

        ema_short = df["EMA_12"].iloc[-1]
        ema_long = df["EMA_26"].iloc[-1]

        if ema_short > ema_long:
            return "uptrend"

        if ema_short < ema_long:
            return "downtrend"

        return "sideways"


    def get_regime(self, df):

        trend = self.detect_trend(df)
        volatility = self.detect_volatility(df)

        return {
            "trend": trend,
            "volatility": volatility
        }