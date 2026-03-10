import numpy as np


class MomentumStrategy:

    def generate_signal(self, df):

        close = df["close"]

        momentum = close.iloc[-1] - close.iloc[-10]

        if momentum > 0:
            return 1

        if momentum < 0:
            return -1

        return 0