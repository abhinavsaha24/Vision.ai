class MeanReversionStrategy:

    def generate_signal(self, df):

        rsi = df["RSI"].iloc[-1]

        if rsi < 30:
            return 1

        if rsi > 70:
            return -1

        return 0