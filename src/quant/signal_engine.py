import numpy as np


class QuantSignalEngine:

    def __init__(self):

        self.weights = {
            "ai": 0.4,
            "momentum": 0.2,
            "mean_reversion": 0.2,
            "sentiment": 0.2
        }

    def ai_signal(self, prediction):

        if prediction["probability"] > 0.6:
            return 1

        if prediction["probability"] < 0.4:
            return -1

        return 0


    def momentum_signal(self, df):

        close = df["close"]

        momentum = close.iloc[-1] - close.iloc[-10]

        if momentum > 0:
            return 1

        if momentum < 0:
            return -1

        return 0


    def mean_reversion_signal(self, df):

        rsi = df["RSI"].iloc[-1]

        if rsi < 30:
            return 1

        if rsi > 70:
            return -1

        return 0


    def sentiment_signal(self, sentiment_score):

        if sentiment_score > 0.2:
            return 1

        if sentiment_score < -0.2:
            return -1

        return 0


    def generate_signal(self, df, prediction, sentiment_score):

        signals = {}

        signals["ai"] = self.ai_signal(prediction)

        signals["momentum"] = self.momentum_signal(df)

        signals["mean_reversion"] = self.mean_reversion_signal(df)

        signals["sentiment"] = self.sentiment_signal(sentiment_score)

        final_score = 0

        for name, signal in signals.items():

            final_score += signal * self.weights[name]

        if final_score > 0:
            return 1

        if final_score < 0:
            return -1

        return 0