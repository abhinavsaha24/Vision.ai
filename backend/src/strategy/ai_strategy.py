class AIStrategy:

    def generate_signal(self, prediction):

        if prediction["probability"] > 0.6:
            return 1

        if prediction["probability"] < 0.4:
            return -1

        return 0
