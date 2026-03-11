import numpy as np


class RegimeDetector:

    """
    Detects current market regime using trend, volatility,
    and momentum indicators.
    """

    def detect_volatility(self, df):

        vol = df["Returns"].rolling(20).std()

        current = vol.iloc[-1]

        avg = vol.mean()

        if current > avg * 1.3:
            return "high_volatility"

        if current < avg * 0.7:
            return "low_volatility"

        return "normal_volatility"


    def detect_trend(self, df):

        ema_short = df["EMA_12"].iloc[-1]
        ema_long = df["EMA_26"].iloc[-1]

        price = df["close"].iloc[-1]

        if ema_short > ema_long and price > ema_short:
            return "strong_uptrend"

        if ema_short < ema_long and price < ema_short:
            return "strong_downtrend"

        if ema_short > ema_long:
            return "weak_uptrend"

        if ema_short < ema_long:
            return "weak_downtrend"

        return "sideways"


    def detect_momentum(self, df):

        rsi = df["RSI"].iloc[-1]

        if rsi > 70:
            return "overbought"

        if rsi < 30:
            return "oversold"

        return "neutral"


    def get_regime(self, df):

        trend = self.detect_trend(df)

        volatility = self.detect_volatility(df)

        momentum = self.detect_momentum(df)

        return {

            "trend": trend,

            "volatility": volatility,

            "momentum": momentum

        }