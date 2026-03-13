"""
Model training with proper walk-forward CV, feature importance, and ensemble.

Models: RandomForest, XGBoost, LightGBM
Supports: time-series split CV, feature importance, SHAP, configurable weights.
"""

from __future__ import annotations

import logging
import joblib
import numpy as np
import pandas as pd

from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import TimeSeriesSplit

import xgboost as xgb
import lightgbm as lgb

logger = logging.getLogger(__name__)


@dataclass
class TrainingMetadata:
    """Metadata about model training."""
    feature_names: List[str] = field(default_factory=list)
    n_train_samples: int = 0
    cv_accuracy_mean: float = 0.0
    cv_accuracy_std: float = 0.0
    accuracy: float = 0.0
    feature_importances: Dict[str, float] = field(default_factory=dict)


class ModelTrainer:

    def __init__(self, model_dir: str = "models", test_size: float = 0.2):

        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(exist_ok=True)

        self.test_size = test_size
        self.scaler = StandardScaler()

        self.rf = RandomForestClassifier(
            n_estimators=300,
            max_depth=8,
            min_samples_leaf=10,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )

        self.xgb = xgb.XGBClassifier(
            n_estimators=300,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_alpha=0.1,
            reg_lambda=1.0,
            random_state=42,
            use_label_encoder=False,
            eval_metric="logloss",
        )

        self.lgb = lgb.LGBMClassifier(
            n_estimators=300,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_alpha=0.1,
            reg_lambda=1.0,
            random_state=42,
            verbose=-1,
        )

        # Ensemble weights (can be tuned)
        self.weights = {"rf": 0.30, "xgb": 0.40, "lgb": 0.30}

        self.feature_names_: List[str] = []
        self.metrics: Dict = {}
        self.metadata = TrainingMetadata()

    # --------------------------------------------------
    # Main training entry point
    # --------------------------------------------------

    def train(self, df: pd.DataFrame, target_col: str = "Target_Direction",
              run_cv: bool = True, n_splits: int = 5):
        """
        Train all models with optional time-series cross-validation.

        Args:
            df: DataFrame with features and target
            target_col: target column name
            run_cv: run TimeSeriesSplit CV
            n_splits: number of CV folds
        """

        # Identify feature columns
        exclude_cols = {"Target", "Target_Direction", target_col}
        feature_cols = [c for c in df.columns if c not in exclude_cols]
        self.feature_names_ = feature_cols
        self.metadata.feature_names = feature_cols

        X = df[feature_cols].values.astype(np.float64)
        y = df[target_col].values.astype(int)

        # Replace any remaining inf/nan
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

        self.metadata.n_train_samples = len(X)

        # --------------------------------------------------
        # Cross-validation (TimeSeriesSplit)
        # --------------------------------------------------

        if run_cv and len(X) > n_splits * 10:
            tscv = TimeSeriesSplit(n_splits=n_splits)
            cv_scores = []

            for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
                X_tr, X_va = X[train_idx], X[val_idx]
                y_tr, y_va = y[train_idx], y[val_idx]

                scaler_cv = StandardScaler()
                X_tr_s = scaler_cv.fit_transform(X_tr)
                X_va_s = scaler_cv.transform(X_va)

                # Quick RF for CV
                rf_cv = RandomForestClassifier(n_estimators=100, max_depth=6, random_state=42, n_jobs=-1)
                rf_cv.fit(X_tr_s, y_tr)
                score = rf_cv.score(X_va_s, y_va)
                cv_scores.append(score)

                logger.info(f"CV Fold {fold + 1}: accuracy={score:.4f}")

            self.metrics["cv_accuracy_mean"] = float(np.mean(cv_scores))
            self.metrics["cv_accuracy_std"] = float(np.std(cv_scores))
            self.metadata.cv_accuracy_mean = self.metrics["cv_accuracy_mean"]
            self.metadata.cv_accuracy_std = self.metrics["cv_accuracy_std"]

        # --------------------------------------------------
        # Full training with train/test split
        # --------------------------------------------------

        split_idx = int(len(X) * (1 - self.test_size))
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]

        X_train_s = self.scaler.fit_transform(X_train)
        X_test_s = self.scaler.transform(X_test)

        # Train RandomForest
        logger.info("Training RandomForest...")
        self.rf.fit(X_train_s, y_train)

        # Train XGBoost
        logger.info("Training XGBoost...")
        self.xgb.fit(X_train_s, y_train)

        # Train LightGBM
        logger.info("Training LightGBM...")
        self.lgb.fit(X_train_s, y_train)

        # Test accuracy (ensemble)
        if len(X_test_s) > 0:
            ensemble_proba = self.predict_proba_ensemble(X_test_s)
            ensemble_pred = (ensemble_proba >= 0.5).astype(int)
            accuracy = float(np.mean(ensemble_pred == y_test))
            self.metrics["accuracy"] = accuracy
            self.metadata.accuracy = accuracy
            logger.info(f"Test accuracy (ensemble): {accuracy:.4f}")

        # Feature importance
        self._compute_feature_importance()

        return {"status": "ensemble trained", "metrics": self.metrics}

    # --------------------------------------------------
    # Ensemble prediction
    # --------------------------------------------------

    def predict_proba_ensemble(self, X_scaled: np.ndarray) -> np.ndarray:
        """Weighted ensemble probability prediction."""
        rf_prob = self.rf.predict_proba(X_scaled)[:, 1]
        xgb_prob = self.xgb.predict_proba(X_scaled)[:, 1]
        lgb_prob = self.lgb.predict_proba(X_scaled)[:, 1]

        combined = (
            rf_prob * self.weights["rf"] +
            xgb_prob * self.weights["xgb"] +
            lgb_prob * self.weights["lgb"]
        )

        return np.clip(combined, 0, 1)

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Legacy method: scale and predict."""
        X_scaled = self.scaler.transform(X)
        return self.predict_proba_ensemble(X_scaled)

    # --------------------------------------------------
    # Feature importance
    # --------------------------------------------------

    def _compute_feature_importance(self):
        """Aggregate feature importance from all models."""
        importance = {}

        # RF importance
        rf_imp = self.rf.feature_importances_
        for i, name in enumerate(self.feature_names_):
            importance[name] = float(rf_imp[i])

        # XGBoost importance
        xgb_imp = self.xgb.feature_importances_
        for i, name in enumerate(self.feature_names_):
            importance[name] = (importance.get(name, 0) + float(xgb_imp[i])) / 2

        # LightGBM importance
        lgb_imp = self.lgb.feature_importances_
        lgb_total = lgb_imp.sum() if lgb_imp.sum() > 0 else 1
        for i, name in enumerate(self.feature_names_):
            importance[name] = (importance.get(name, 0) * 2 + float(lgb_imp[i] / lgb_total)) / 3

        # Sort by importance
        self.metadata.feature_importances = dict(
            sorted(importance.items(), key=lambda x: x[1], reverse=True)
        )
        self.metrics["top_features"] = list(self.metadata.feature_importances.keys())[:15]

    def get_feature_importance(self, top_n: int = 20) -> Dict[str, float]:
        """Return top-N most important features."""
        return dict(list(self.metadata.feature_importances.items())[:top_n])

    # --------------------------------------------------
    # Save / Load
    # --------------------------------------------------

    def save(self, name: str = "trading_model"):

        joblib.dump(self.rf, self.model_dir / f"{name}_rf.joblib")
        joblib.dump(self.xgb, self.model_dir / f"{name}_xgb.joblib")
        joblib.dump(self.lgb, self.model_dir / f"{name}_lgb.joblib")
        joblib.dump(self.scaler, self.model_dir / f"{name}_scaler.joblib")
        joblib.dump(self.feature_names_, self.model_dir / f"{name}_features.joblib")
        joblib.dump(self.metadata, self.model_dir / f"{name}_metadata.joblib")
        joblib.dump(self.weights, self.model_dir / f"{name}_weights.joblib")

        logger.info(f"Models saved: {name}")

    def load(self, name: str = "trading_model"):

        self.rf = joblib.load(self.model_dir / f"{name}_rf.joblib")
        self.xgb = joblib.load(self.model_dir / f"{name}_xgb.joblib")
        self.lgb = joblib.load(self.model_dir / f"{name}_lgb.joblib")
        self.scaler = joblib.load(self.model_dir / f"{name}_scaler.joblib")
        self.feature_names_ = joblib.load(self.model_dir / f"{name}_features.joblib")

        # Load optional metadata
        meta_path = self.model_dir / f"{name}_metadata.joblib"
        if meta_path.exists():
            self.metadata = joblib.load(meta_path)

        weights_path = self.model_dir / f"{name}_weights.joblib"
        if weights_path.exists():
            self.weights = joblib.load(weights_path)

        # Backward compatibility
        if hasattr(self, 'feature_names') and not self.feature_names_:
            self.feature_names_ = self.feature_names

        logger.info(f"Models loaded: {name}")