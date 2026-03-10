from src.data_collection.fetcher import DataFetcher
from src.feature_engineering.indicators import FeatureEngineer
from src.model_training.trainer import ModelTrainer
from src.prediction.ensemble_model import EnsembleModel

import numpy as np


class Predictor:
    """
    Handles full prediction pipeline:
    fetch data -> build features -> run ensemble -> return signals
    """

    def __init__(self):

        self.fetcher = DataFetcher()
        self.engineer = FeatureEngineer()

        self.trainer = ModelTrainer()
        self.trainer.load("trading_model")

        # if trainer contains multiple models
        if hasattr(self.trainer, "models"):

            self.ensemble = EnsembleModel(self.trainer.models)

        else:
            self.ensemble = None

    def predict_symbol(self, symbol="BTC/USDT", horizon=5):

        try:

            df = self.fetcher.fetch(symbol)

            if df is None or df.empty:
                raise ValueError("No market data fetched")

            df = self.engineer.add_all_indicators(df)

            df = df.dropna()

            if len(df) < 50:
                raise ValueError("Not enough data for prediction")

            # ensure correct feature order
            X = df[self.trainer.feature_names].values

            # run prediction
            if self.ensemble:

                probs = self.ensemble.predict_proba(X)

            else:

                probs = self.trainer.predict(X)

            predictions = []

            for i in range(1, horizon + 1):

                p = probs[-i]

                predictions.append(
                    {
                        "step": i,
                        "direction": "UP" if p >= 0.5 else "DOWN",
                        "probability": float(np.round(p, 4)),
                    }
                )

            return predictions

        except Exception as e:

            print(f"Prediction error for {symbol}: {e}")

            return []