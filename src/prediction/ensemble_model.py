"""
Ensemble model: combines predictions from multiple ML models.

Supports:
  - Weighted averaging
  - Stacking (meta-learner)
  - Per-model confidence
  - Structured output: prob_up, prob_down, volatility_forecast, confidence
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import Dict, Optional

from sklearn.linear_model import LogisticRegression


@dataclass
class EnsemblePrediction:
    """Structured prediction output from ensemble."""
    prob_up: float
    prob_down: float
    volatility_forecast: float
    confidence: float
    direction: str  # "UP", "DOWN", "NEUTRAL"
    model_agreement: float  # 0-1, how much models agree


class EnsembleModel:
    """
    Combines predictions from multiple ML models.

    Supports:
    - RandomForest, XGBoost, LightGBM
    - Optional deep learning models
    - Weighted averaging or stacking
    """

    def __init__(self, models: Dict[str, object], weights: Optional[Dict[str, float]] = None):
        """
        Args:
            models: dict like {"rf": model1, "xgb": model2, "lgb": model3}
            weights: optional weights (must sum to 1.0)
        """
        self.models = models

        if weights is None:
            n = len(models)
            self.weights = {name: 1 / n for name in models}
        else:
            self.weights = weights

        self.meta_learner = None

    # --------------------------------------------------
    # Weighted averaging
    # --------------------------------------------------

    def predict_proba(self, X) -> np.ndarray:
        """Weighted average of model probabilities."""

        all_probs = {}
        weighted_probs = []

        for name, model in self.models.items():
            try:
                p = model.predict_proba(X)[:, 1]
                all_probs[name] = p
                weight = self.weights.get(name, 0)
                weighted_probs.append(p * weight)
            except Exception as e:
                print(f"Model {name} failed: {e}")

        if len(weighted_probs) == 0:
            raise ValueError("No models produced predictions")

        final_prob = np.sum(weighted_probs, axis=0)
        return np.clip(final_prob, 0, 1)

    def predict(self, X, threshold: float = 0.5) -> np.ndarray:
        prob = self.predict_proba(X)
        return (prob >= threshold).astype(int)

    # --------------------------------------------------
    # Per-model probabilities (for stacking/analysis)
    # --------------------------------------------------

    def predict_all_models(self, X) -> Dict[str, np.ndarray]:
        """Return individual model probabilities."""
        results = {}
        for name, model in self.models.items():
            try:
                results[name] = model.predict_proba(X)[:, 1]
            except Exception:
                pass
        return results

    # --------------------------------------------------
    # Stacking ensemble
    # --------------------------------------------------

    def fit_stacking(self, X, y):
        """Train a meta-learner on base model outputs."""
        base_preds = []
        for name, model in self.models.items():
            try:
                p = model.predict_proba(X)[:, 1]
                base_preds.append(p)
            except Exception:
                pass

        if len(base_preds) < 2:
            return

        meta_X = np.column_stack(base_preds)
        self.meta_learner = LogisticRegression(random_state=42)
        self.meta_learner.fit(meta_X, y)

    def predict_stacking(self, X) -> np.ndarray:
        """Predict using stacking ensemble."""
        if self.meta_learner is None:
            return self.predict_proba(X)

        base_preds = []
        for name, model in self.models.items():
            try:
                base_preds.append(model.predict_proba(X)[:, 1])
            except Exception:
                pass

        meta_X = np.column_stack(base_preds)
        return self.meta_learner.predict_proba(meta_X)[:, 1]

    # --------------------------------------------------
    # Structured prediction
    # --------------------------------------------------

    def predict_structured(self, X, volatility_data: Optional[np.ndarray] = None) -> list:
        """
        Return structured predictions with confidence and agreement.

        Args:
            X: feature matrix
            volatility_data: optional volatility values for each sample
        """
        all_model_probs = self.predict_all_models(X)
        ensemble_prob = self.predict_proba(X)

        predictions = []
        for i in range(len(ensemble_prob)):
            prob_up = float(ensemble_prob[i])
            prob_down = 1.0 - prob_up

            # Model agreement (std of individual model predictions)
            model_preds_i = [probs[i] for probs in all_model_probs.values()]
            if len(model_preds_i) > 1:
                agreement = 1.0 - float(np.std(model_preds_i)) * 2  # 0=disagree, 1=agree
                agreement = max(0.0, min(1.0, agreement))
            else:
                agreement = 1.0

            # Confidence based on probability strength and agreement
            prob_strength = abs(prob_up - 0.5) * 2  # 0=uncertain, 1=certain
            confidence = prob_strength * agreement

            # Direction
            if prob_up > 0.55:
                direction = "UP"
            elif prob_up < 0.45:
                direction = "DOWN"
            else:
                direction = "NEUTRAL"

            # Volatility forecast (pass-through if provided)
            vol = float(volatility_data[i]) if volatility_data is not None and i < len(volatility_data) else 0.0

            predictions.append(EnsemblePrediction(
                prob_up=round(prob_up, 4),
                prob_down=round(prob_down, 4),
                volatility_forecast=round(vol, 6),
                confidence=round(confidence, 4),
                direction=direction,
                model_agreement=round(agreement, 4),
            ))

        return predictions