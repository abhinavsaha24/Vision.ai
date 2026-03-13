"""
Predictor: orchestrates data → features → model → prediction pipeline.

Features:
  - Regime-aware predictions
  - Confidence-adjusted output
  - Volatility forecast
  - Multi-step predictions
"""

from __future__ import annotations

import logging
import numpy as np
from typing import Dict, List, Optional

from backend.src.data.fetcher import DataFetcher
from backend.src.features.indicators import FeatureEngineer
from backend.src.models.trainer import ModelTrainer
from backend.src.models.regime_detector import MarketRegimeDetector

logger = logging.getLogger(__name__)


class Predictor:
    """Full prediction pipeline: fetch → features → predict → signal."""

    def __init__(self, model_name: str = "trading_model"):

        self.fetcher = DataFetcher()
        self.engineer = FeatureEngineer()
        self.regime_detector = MarketRegimeDetector()

        self.trainer = ModelTrainer()

        try:
            self.trainer.load(model_name)
            self._model_loaded = True
            logger.info(f"Predictor loaded model: {model_name}")
        except Exception as e:
            self._model_loaded = False
            logger.warning(f"Model not loaded: {e}")

    def predict_symbol(self, symbol: str = "BTC/USDT", horizon: int = 5) -> List[Dict]:
        """
        Generate predictions for a symbol.

        Returns list of prediction dicts:
        [
            {step, direction, probability, confidence, regime}
        ]
        """

        try:
            # 1. Fetch market data
            df = self.fetcher.fetch(symbol)

            if df is None or df.empty:
                raise ValueError("No market data fetched")

            # 2. Generate features
            df = self.engineer.add_all_indicators(df, add_target=False)
            df = df.dropna()

            if len(df) < 50:
                raise ValueError(f"Not enough data ({len(df)} rows)")

            # 3. Detect regime
            regime = self.regime_detector.get_regime(df)

            # 4. Run model prediction
            if not self._model_loaded:
                raise ValueError("No trained model available")

            # Ensure correct feature order
            feature_names = self.trainer.feature_names_
            missing = set(feature_names) - set(df.columns)

            if missing:
                logger.warning(f"Missing features: {missing} — filling with 0")
                for col in missing:
                    df[col] = 0

            X = df[feature_names].values
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

            # Scale and predict
            X_scaled = self.trainer.scaler.transform(X)
            probs = self.trainer.predict_proba_ensemble(X_scaled)

            # 5. Get volatility for confidence adjustment
            volatility = float(df["volatility_20"].iloc[-1]) if "volatility_20" in df.columns else 0.0

            # 6. Build predictions
            predictions = []

            for i in range(1, min(horizon + 1, len(probs) + 1)):
                p = float(probs[-i])

                # Confidence (probability strength × volatility adjustment)
                prob_strength = abs(p - 0.5) * 2
                vol_penalty = max(0.5, 1.0 - volatility * 10)  # lower confidence in high vol
                confidence = prob_strength * vol_penalty

                predictions.append({
                    "step": i,
                    "direction": "UP" if p >= 0.5 else "DOWN",
                    "probability": round(p, 4),
                    "confidence": round(confidence, 4),
                    "regime": regime.get("label", "unknown"),
                })

            return predictions

        except Exception as e:
            logger.error(f"Prediction error for {symbol}: {e}")
            return []

    def predict_with_features(self, df, feature_names: Optional[List[str]] = None) -> np.ndarray:
        """
        Predict on pre-engineered DataFrame.
        Returns raw probabilities.
        """
        if not self._model_loaded:
            raise ValueError("No model loaded")

        names = feature_names or self.trainer.feature_names_
        X = df[names].values
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        X_scaled = self.trainer.scaler.transform(X)

        return self.trainer.predict_proba_ensemble(X_scaled)