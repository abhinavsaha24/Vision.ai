class ConfidenceEngine:

    def calculate_confidence(self, probability):

        if probability > 0.7:
            return "HIGH"

        if probability > 0.55:
            return "MEDIUM"

        return "LOW"