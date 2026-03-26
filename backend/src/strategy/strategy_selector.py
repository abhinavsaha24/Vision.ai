class StrategySelector:

    def select_strategy(self, regime):
        market_state = str(regime.get("market_state", "")).upper()
        trend = str(regime.get("trend", "sideways"))

        if market_state == "VOLATILE":
            return "reduced_risk"

        if market_state == "TREND":
            return "momentum" if trend in {"uptrend", "downtrend"} else "momentum"

        if market_state == "RANGE":
            return "mean_reversion"

        return "mean_reversion"
