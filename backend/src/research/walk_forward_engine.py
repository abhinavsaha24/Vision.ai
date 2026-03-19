"""Institutional walk-forward engine with leakage-safe rolling retraining."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (accuracy_score, f1_score, precision_score,
                             recall_score, roc_auc_score)


@dataclass
class WalkForwardWindowResult:
    window_id: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    accuracy: float
    precision: float
    recall: float
    f1: float
    roc_auc: float


class WalkForwardEngine:
    """Runs strict rolling walk-forward validation with per-window retraining."""

    def __init__(self, n_splits: int = 6, train_ratio: float = 0.7):
        self.n_splits = n_splits
        self.train_ratio = train_ratio

    def run(
        self,
        df: pd.DataFrame,
        feature_cols: List[str],
        target_col: str = "Target_Direction",
        model_factory: Optional[Callable[[], Any]] = None,
    ) -> Dict:
        if len(df) < 150:
            return {"error": "insufficient_data"}
        if target_col not in df.columns:
            return {"error": f"missing target column: {target_col}"}

        model_factory = model_factory or (
            lambda: RandomForestClassifier(
                n_estimators=400,
                max_depth=10,
                min_samples_leaf=8,
                class_weight="balanced",
                random_state=42,
                n_jobs=-1,
            )
        )

        n = len(df)
        win_size = n // self.n_splits
        windows: List[WalkForwardWindowResult] = []

        for i in range(self.n_splits):
            start = i * win_size
            end = min(n, (i + 1) * win_size)
            if end - start < 25:
                continue

            train_end = start + int((end - start) * self.train_ratio)
            test_start = train_end
            test_end = end
            if test_end - test_start < 10:
                continue

            train_df = df.iloc[start:train_end].copy()
            test_df = df.iloc[test_start:test_end].copy()

            X_train = (
                train_df[feature_cols]
                .replace([np.inf, -np.inf], np.nan)
                .fillna(0.0)
                .values
            )
            y_train = np.asarray(train_df[target_col].astype(int).values)
            X_test = (
                test_df[feature_cols]
                .replace([np.inf, -np.inf], np.nan)
                .fillna(0.0)
                .values
            )
            y_test = np.asarray(test_df[target_col].astype(int).values)

            model = model_factory()
            model.fit(X_train, y_train)
            proba = model.predict_proba(X_test)[:, 1]
            pred = (proba >= 0.5).astype(int)

            windows.append(
                WalkForwardWindowResult(
                    window_id=i + 1,
                    train_start=str(train_df.index[0])[:10],
                    train_end=str(train_df.index[-1])[:10],
                    test_start=str(test_df.index[0])[:10],
                    test_end=str(test_df.index[-1])[:10],
                    accuracy=float(accuracy_score(y_test, pred)),
                    precision=float(precision_score(y_test, pred, zero_division=0)),
                    recall=float(recall_score(y_test, pred, zero_division=0)),
                    f1=float(f1_score(y_test, pred, zero_division=0)),
                    roc_auc=(
                        float(roc_auc_score(y_test, proba))
                        if len(np.unique(y_test)) > 1
                        else 0.5
                    ),
                )
            )

        if not windows:
            return {"error": "no_valid_windows"}

        return {
            "n_windows": len(windows),
            "avg_accuracy": float(np.mean([w.accuracy for w in windows])),
            "avg_precision": float(np.mean([w.precision for w in windows])),
            "avg_recall": float(np.mean([w.recall for w in windows])),
            "avg_f1": float(np.mean([w.f1 for w in windows])),
            "avg_roc_auc": float(np.mean([w.roc_auc for w in windows])),
            "windows": [w.__dict__ for w in windows],
        }
