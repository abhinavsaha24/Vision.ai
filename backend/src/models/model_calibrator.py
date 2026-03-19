"""Probability calibration helpers for institutional thresholding."""

from __future__ import annotations

from typing import Dict, Literal, cast

import numpy as np
from sklearn.calibration import CalibratedClassifierCV


class ModelCalibrator:
    """Wraps sklearn calibration to improve probability reliability."""

    def __init__(
        self, method: Literal["sigmoid", "isotonic"] = "isotonic", cv: int = 3
    ):
        self.method = method
        self.cv = cv
        self.calibrated_model = None

    def fit(self, base_model, X, y):
        self.calibrated_model = CalibratedClassifierCV(
            base_model,
            method=cast(Literal["sigmoid", "isotonic"], self.method),
            cv=self.cv,
        )
        self.calibrated_model.fit(X, y)
        return self

    def predict_proba(self, X) -> np.ndarray:
        if self.calibrated_model is None:
            raise RuntimeError("ModelCalibrator is not fitted")
        return self.calibrated_model.predict_proba(X)[:, 1]

    @staticmethod
    def reliability_bins(
        y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10
    ) -> Dict:
        y_true = np.asarray(y_true).astype(int)
        y_prob = np.asarray(y_prob, dtype=float)

        bins = np.linspace(0, 1, n_bins + 1)
        rows = []
        ece = 0.0

        for i in range(n_bins):
            lo, hi = bins[i], bins[i + 1]
            mask = (y_prob >= lo) & (y_prob < hi if i < n_bins - 1 else y_prob <= hi)
            count = int(mask.sum())
            if count == 0:
                rows.append({"bin": i, "count": 0, "mean_prob": 0.0, "empirical": 0.0})
                continue
            mean_prob = float(y_prob[mask].mean())
            empirical = float(y_true[mask].mean())
            weight = count / max(len(y_true), 1)
            ece += abs(mean_prob - empirical) * weight
            rows.append(
                {
                    "bin": i,
                    "count": count,
                    "mean_prob": mean_prob,
                    "empirical": empirical,
                }
            )

        return {"bins": rows, "ece": float(ece)}
