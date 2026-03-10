from src.strategy.ai_strategy import AIStrategy
from src.strategy.momentum_strategy import MomentumStrategy
from src.strategy.mean_reversion import MeanReversionStrategy


class StrategyEngine:
    """
    Combines multiple strategies and produces a final trading signal.
    """

    def __init__(self):

        self.ai = AIStrategy()
        self.momentum = MomentumStrategy()
        self.mean_reversion = MeanReversionStrategy()

        # strategy weights
        self.weights = {
            "ai": 0.5,
            "momentum": 0.3,
            "mean_reversion": 0.2
        }

        # minimum AI confidence to consider signal
        self.ai_threshold = 0.55

    def generate_signal(self, df, prediction):

        signals = []

        # ---------------- AI STRATEGY ----------------
        ai_signal = self.ai.generate_signal(prediction)

        if prediction["probability"] >= self.ai_threshold:
            signals.append(ai_signal * self.weights["ai"])
        else:
            signals.append(0)

        # ---------------- MOMENTUM ----------------
        momentum_signal = self.momentum.generate_signal(df)
        signals.append(momentum_signal * self.weights["momentum"])

        # ---------------- MEAN REVERSION ----------------
        mr_signal = self.mean_reversion.generate_signal(df)
        signals.append(mr_signal * self.weights["mean_reversion"])

        # ---------------- FINAL VOTE ----------------
        score = sum(signals)

        if score > 0.1:
            return 1

        if score < -0.1:
            return -1

        return 0