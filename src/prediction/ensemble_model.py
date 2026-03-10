import numpy as np
from typing import Dict


class EnsembleModel:
    """
    Combines predictions from multiple ML models using weighted averaging.

    Supports:
    - RandomForest
    - XGBoost
    - LightGBM
    """

    def __init__(self, models: Dict[str, object], weights: Dict[str, float] = None):
        """
        models: dict like {"rf": model1, "xgb": model2, "lgb": model3}

        weights: optional weights for models
        example:
        {"rf": 0.3, "xgb": 0.4, "lgb": 0.3}
        """

        self.models = models

        if weights is None:
            # default equal weights
            n = len(models)
            self.weights = {name: 1 / n for name in models}
        else:
            self.weights = weights

    def predict_proba(self, X):

        weighted_probs = []

        for name, model in self.models.items():

            try:
                p = model.predict_proba(X)[:, 1]

                weight = self.weights.get(name, 0)

                weighted_probs.append(p * weight)

            except Exception as e:
                print(f"Model {name} failed during prediction: {e}")

        if len(weighted_probs) == 0:
            raise ValueError("No models produced predictions")

        final_prob = np.sum(weighted_probs, axis=0)

        # ensure probability bounds
        final_prob = np.clip(final_prob, 0, 1)

        return final_prob

    def predict(self, X, threshold: float = 0.5):

        prob = self.predict_proba(X)

        return (prob >= threshold).astype(int)