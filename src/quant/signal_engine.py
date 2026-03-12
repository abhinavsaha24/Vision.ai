import numpy as np


class QuantSignalEngine:

    """
    Combines multiple signals into a final trading decision.

    Signals used:
    - AI prediction
    - Momentum
    - Mean Reversion (RSI)
    - Sentiment
    """

    def __init__(self):

        self.weights = {
            "ai": 0.4,
            "momentum": 0.2,
            "mean_reversion": 0.2,
            "sentiment": 0.2
        }

    # -----------------------------
    # AI Signal
    # -----------------------------

    def ai_signal(self, prediction):

        prob = prediction["probability"]

        if prob > 0.6:
            return 1

        if prob < 0.4:
            return -1

        return 0

    # -----------------------------
    # Momentum Signal
    # -----------------------------

def momentum_signal(self, df):

    if "close" not in df.columns:
        return 0

    if len(df) < 10:
        return 0

    close = df["close"]

    momentum = close.iloc[-1] - close.iloc[-10]

    if momentum > 0:
        return 1

    if momentum < 0:
        return -1

    return 0

    # -----------------------------
    # Mean Reversion (RSI)
    # -----------------------------

    def mean_reversion_signal(self, df):

        if "RSI" not in df.columns:
            return 0

        rsi = df["RSI"].iloc[-1]

        if rsi < 30:
            return 1

        if rsi > 70:
            return -1

        return 0

    # -----------------------------
    # Sentiment Signal
    # -----------------------------

    def sentiment_signal(self, sentiment_score):

        if sentiment_score > 0.2:
            return 1

        if sentiment_score < -0.2:
            return -1

        return 0

    # -----------------------------
    # Final Signal Aggregation
    # -----------------------------

    def generate_signal(self, df, prediction, sentiment_score=0):

        signals = {}

        signals["ai"] = self.ai_signal(prediction)

        signals["momentum"] = self.momentum_signal(df)

        signals["mean_reversion"] = self.mean_reversion_signal(df)

        signals["sentiment"] = self.sentiment_signal(sentiment_score)

        # weighted score
        final_score = 0

        for name, signal in signals.items():

            weight = self.weights.get(name, 0)

            final_score += signal * weight

        # normalize score
        final_score = round(final_score, 3)

        # determine direction
        if final_score > 0.1:
            direction = "BUY"

        elif final_score < -0.1:
            direction = "SELL"

        else:
            direction = "HOLD"

        return {
            "direction": direction,
            "score": final_score,
            "signals": signals
        }