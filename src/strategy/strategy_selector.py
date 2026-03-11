class StrategySelector:

    def select_strategy(self, regime):

        if regime == "BULL":
            return "momentum"

        if regime == "BEAR":
            return "mean_reversion"

        return "range_trading"