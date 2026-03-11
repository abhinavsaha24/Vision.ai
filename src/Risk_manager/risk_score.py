import numpy as np

class RiskScore:

    def calculate_risk(self, df):

        volatility = df["close"].pct_change().std()

        if volatility > 0.03:
            return "HIGH"

        if volatility > 0.015:
            return "MEDIUM"

        return "LOW"