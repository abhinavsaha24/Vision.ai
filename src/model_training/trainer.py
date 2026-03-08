"""
Model training with RandomForest, XGBoost, LightGBM, time-series CV, and ensemble.

- Dataset is split by time before any fitting (no leakage).
- Scaler fitted on train only; applied to train and test.
- Feature importance computed from trained models.
- Ensemble combines model probabilities with configurable weights.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

# Try optional dependencies
try:
    import xgboost as xgb
    HAS_XGB = True
except ImportError:
    HAS_XGB = False
try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:
    HAS_LGB = False

# All feature columns produced by FeatureEngineer (excluding target)
FEATURE_COLUMNS = [
    "candle_body",
    "upper_wick",
    "lower_wick",
    "candle_range",
    "volume_moving_average",
    "volume_ratio",
    "volume_momentum",
    "momentum_10",
    "momentum_20",
    "price_rate_of_change",
    "ema_slope",
    "sma_slope",
    "SMA_7",
    "SMA_21",
    "SMA_50",
    "EMA_12",
    "EMA_26",
    "RSI",
    "MACD",
    "MACD_Signal",
    "MACD_Histogram",
    "BB_Middle",
    "BB_Upper",
    "BB_Lower",
    "BB_Width",
    "Returns",
    "Log_Returns",
    "Volatility_20",
    # Lagged returns
    "returns_lag_1",
    "returns_lag_3",
    "returns_lag_5",
    "returns_lag_10",
    # Statistical
    "rolling_skewness_20",
    "rolling_kurtosis_20",
    "rolling_zscore_returns",
    # Volatility indicators
    "ATR",
    "realized_volatility",
    "volatility_ratio",
    # Calendar
    "hour_of_day",
    "day_of_week",
    "weekend",
    # Regime
    "trend_strength",
    "volatility_regime",
]

# Default ensemble weights: RF 0.3, XGB 0.4, LGB 0.3
DEFAULT_ENSEMBLE_WEIGHTS = {"rf": 0.3, "xgb": 0.4, "lgb": 0.3}


def _get_available_models() -> List[str]:
    out = ["rf"]
    if HAS_XGB:
        out.append("xgb")
    if HAS_LGB:
        out.append("lgb")
    return out


class ModelTrainer:
    """
    Trains RF, XGBoost, and LightGBM with time-series split and optional ensemble.
    No data leakage: split is done first; scaler and models see only training data.
    """

    def __init__(
        self,
        model_dir: str | Path = "models",
        test_size: float = 0.2,
        random_state: int = 42,
        n_splits: int = 5,
    ) -> None:
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.test_size = test_size
        self.random_state = random_state
        self.n_splits = n_splits
        self.scaler = StandardScaler()
        self.models: Dict[str, Any] = {}
        self.feature_names_: List[str] = []
        self.metrics: Dict[str, Any] = {}
        self.cv_scores_: List[float] = []

    def _prepare_X_y(
        self,
        df: pd.DataFrame,
        target_col: str = "Target_Direction",
    ) -> Tuple[np.ndarray, np.ndarray, List[str]]:
        """Extract feature matrix and target; use only columns that exist."""
        available = [c for c in FEATURE_COLUMNS if c in df.columns]
        if not available:
            raise ValueError("No feature columns found in DataFrame")
        X = df[available].astype(float).values
        y = df[target_col].dropna()
        # Align X to rows that have valid target
        valid_idx = df.loc[df[target_col].notna()].index
        X = df.loc[valid_idx, available].astype(float).values
        y = df.loc[valid_idx, target_col].astype(int).values
        return X, y, available

    def _split_time(
        self,
        X: np.ndarray,
        y: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Time-based split: first (1-test_size) for train, last test_size for test."""
        n = len(X)
        split_idx = int(n * (1 - self.test_size))
        if split_idx < 10:
            split_idx = max(1, n - 50)
        return (
            X[:split_idx],
            X[split_idx:],
            y[:split_idx],
            y[split_idx:],
        )

    def fit_models(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        feature_names: List[str],
    ) -> None:
        """Fit RF, XGB, LGB on training data only (no test data used)."""
        self.feature_names_ = feature_names
        X_tr = self.scaler.fit_transform(X_train)
        X_tr_df = pd.DataFrame(X_tr, columns=feature_names)

        # RandomForest: 500 trees, tuned depth and leaf params
        self.models["rf"] = RandomForestClassifier(
            n_estimators=500,
            max_depth=12,
            min_samples_split=10,
            min_samples_leaf=4,
            random_state=self.random_state,
            n_jobs=-1,
        )
        self.models["rf"].fit(X_tr, y_train)

        if HAS_XGB:
            self.models["xgb"] = xgb.XGBClassifier(
                n_estimators=300,
                max_depth=6,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=self.random_state,
                eval_metric="logloss",
            )
            self.models["xgb"].fit(X_tr, y_train)

        if HAS_LGB:
            self.models["lgb"] = lgb.LGBMClassifier(
                n_estimators=300,
                max_depth=6,
                learning_rate=0.05,
                num_leaves=31,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=self.random_state,
                verbose=-1,
            )
            self.models["lgb"].fit(X_tr_df, y_train)

    def time_series_cv(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: List[str],
    ) -> List[float]:
        """Run TimeSeriesSplit CV using RF only for speed; returns list of test accuracies."""
        tscv = TimeSeriesSplit(n_splits=self.n_splits)
        scores: List[float] = []
        for train_idx, test_idx in tscv.split(X):
            X_tr, X_te = X[train_idx], X[test_idx]
            y_tr, y_te = y[train_idx], y[test_idx]
            scaler = StandardScaler()
            X_tr_s = scaler.fit_transform(X_tr)
            X_te_s = scaler.transform(X_te)
            clf = RandomForestClassifier(
                n_estimators=200,
                max_depth=10,
                min_samples_split=10,
                min_samples_leaf=4,
                random_state=self.random_state,
                n_jobs=-1,
            )
            clf.fit(X_tr_s, y_tr)
            acc = (clf.predict(X_te_s) == y_te).mean()
            scores.append(float(acc))
        self.cv_scores_ = scores
        return scores

    def train(
        self,
        df: pd.DataFrame,
        target_col: str = "Target_Direction",
        run_cv: bool = True,
    ) -> Dict[str, Any]:
        """
        Split by time, fit scaler and models on train, evaluate on test.
        Returns classification metrics and feature importance.
        """
        # Drop rows with NaN target (e.g. last horizon rows)
        df = df.dropna(subset=[target_col])
        X, y, feature_names = self._prepare_X_y(df, target_col)
        X_train, X_test, y_train, y_test = self._split_time(X, y)

        if run_cv:
            self.time_series_cv(X_train, y_train, feature_names)
            self.metrics["cv_accuracy_mean"] = float(np.mean(self.cv_scores_))
            self.metrics["cv_accuracy_std"] = float(np.std(self.cv_scores_))

        self.fit_models(X_train, y_train, feature_names)
        X_test_scaled = self.scaler.transform(X_test)

        # Ensemble probabilities and predictions
        proba = self.predict_proba_ensemble(X_test_scaled)
        y_pred = (proba >= 0.5).astype(int)

        # Classification metrics
        from src.evaluation.metrics import compute_classification_metrics

        clf_metrics = compute_classification_metrics(y_test, y_pred)
        self.metrics["accuracy"] = clf_metrics.accuracy
        self.metrics["precision"] = clf_metrics.precision
        self.metrics["recall"] = clf_metrics.recall
        self.metrics["f1"] = clf_metrics.f1
        self.metrics["confusion_matrix"] = clf_metrics.confusion_matrix
        self.metrics["train_samples"] = len(X_train)
        self.metrics["test_samples"] = len(X_test)
        self.metrics["features"] = feature_names

        # Feature importance (RF)
        self.metrics["feature_importance"] = dict(
            zip(
                feature_names,
                self.models["rf"].feature_importances_.tolist(),
            )
        )
        return self.metrics

    def predict_proba_ensemble(
        self,
        X: np.ndarray,
        weights: Optional[Dict[str, float]] = None,
    ) -> np.ndarray:
        """
        Combined probability from RF, XGB, LGB using weights.
        Returns 1d array of P(class=1) per row.
        """
        weights = weights or DEFAULT_ENSEMBLE_WEIGHTS
        available = _get_available_models()
        probs: List[np.ndarray] = []
        w_sum = 0.0
        for name in available:
            if name not in self.models:
                continue
            model = self.models[name]
            w = weights.get(name, 0.0)
            if w <= 0:
                continue
            # LightGBM was fitted with DataFrame; pass DataFrame to avoid warning
            X_in = pd.DataFrame(X, columns=self.feature_names_) if name == "lgb" and self.feature_names_ else X
            p = model.predict_proba(X_in)
            if p.shape[1] == 2:
                p1 = p[:, 1]
            else:
                p1 = p.ravel()
            probs.append(p1 * w)
            w_sum += w
        if not probs:
            raise RuntimeError("No models available for ensemble")
        combined = np.sum(probs, axis=0) / (w_sum or 1.0)
        return combined

    def predict_ensemble(
        self,
        X: np.ndarray,
        threshold: float = 0.5,
        weights: Optional[Dict[str, float]] = None,
    ) -> np.ndarray:
        """Binary predictions from ensemble probability."""
        proba = self.predict_proba_ensemble(X, weights=weights)
        return (proba >= threshold).astype(int)

    def save(self, name: str = "trading_model") -> Path:
        """Save scaler, all models, and metrics."""
        base = self.model_dir / name
        joblib.dump(self.scaler, f"{base}_scaler.joblib")
        for k, m in self.models.items():
            joblib.dump(m, f"{base}_{k}.joblib")
        def _to_serializable(obj: Any) -> Any:
            if isinstance(obj, (np.floating, np.integer)):
                return float(obj)
            if isinstance(obj, dict):
                return {k: _to_serializable(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_to_serializable(v) for v in obj]
            return obj

        with open(f"{base}_metrics.json", "w") as f:
            json.dump(_to_serializable(self.metrics), f, indent=2)
        with open(f"{base}_features.json", "w") as f:
            json.dump(self.feature_names_, f)
        return base

    def load(self, name: str = "trading_model") -> ModelTrainer:
        """Load scaler, models, and metadata."""
        base = Path(self.model_dir) / name
        self.scaler = joblib.load(str(base) + "_scaler.joblib")
        self.models = {}
        for key in ["rf", "xgb", "lgb"]:
            path = Path(str(base) + f"_{key}.joblib")
            if path.exists():
                self.models[key] = joblib.load(str(path))
        with open(str(base) + "_metrics.json") as f:
            self.metrics = json.load(f)
        with open(str(base) + "_features.json") as f:
            self.feature_names_ = json.load(f)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Binary class predictions from ensemble (for backward compatibility)."""
        X_scaled = self.scaler.transform(X)
        return self.predict_ensemble(X_scaled)

    def train_from_symbol(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
        save_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch data, generate features, train models. Returns metrics. Optional save."""
        from src.data_collection.fetcher import DataFetcher
        from src.feature_engineering.indicators import FeatureEngineer

        fetcher = DataFetcher()
        df = fetcher.fetch(symbol, period=period, interval=interval)
        engineer = FeatureEngineer()
        df = engineer.add_all_indicators(df)
        df = df.dropna(subset=["Target_Direction"])
        metrics = self.train(df, run_cv=True)
        if save_name:
            self.save(save_name)
        return metrics

    def predict_from_symbol(
        self,
        symbol: str,
        period: str = "1y",
        horizon: int = 5,
    ) -> List[Dict[str, Any]]:
        """Fetch data, add features, return ensemble predictions for last `horizon` rows."""
        from src.data_collection.fetcher import DataFetcher
        from src.feature_engineering.indicators import FeatureEngineer

        fetcher = DataFetcher()
        df = fetcher.fetch(symbol, period=period)
        engineer = FeatureEngineer()
        df = engineer.add_all_indicators(df)
        df = df.dropna(subset=["Target_Direction"])
        available = [c for c in FEATURE_COLUMNS if c in df.columns]
        if not available:
            available = self.feature_names_ if self.feature_names_ else list(df.columns)
            available = [c for c in available if c in df.columns and c not in ("Target", "Target_Direction")]
        X = df[available].astype(float).values
        if not len(self.models):
            self.train(df)
        X_scaled = self.scaler.transform(X)
        proba = self.predict_proba_ensemble(X_scaled)
        pred = (proba >= 0.5).astype(int)
        direction_map = {1: "UP", 0: "DOWN"}
        out = [
            {"day": i + 1, "direction": direction_map.get(int(p), "UNKNOWN"), "probability": float(proba[i])}
            for i, p in enumerate(pred[-horizon:])
        ]
        return out
