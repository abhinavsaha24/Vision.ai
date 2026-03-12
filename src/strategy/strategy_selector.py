class StrategySelector:

    def select_strategy(self, regime):

        trend = regime["trend"]
        volatility = regime["volatility"]

        if volatility == "high_volatility":
            return "ai_strategy"

        if trend == "uptrend":
            return "momentum"

        if trend == "downtrend":
            return "mean_reversion"

        return "mean_reversion"