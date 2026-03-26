"""Cross-validation by market regime and regime robustness diagnostics."""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd
from sklearn.metrics import (accuracy_score, f1_score, precision_score,
                             recall_score, roc_auc_score)


class RegimeAnalysis:
    """Computes model performance segmented by market regimes."""

    @staticmethod
    def classify_regimes(df: pd.DataFrame) -> Dict[str, pd.Series]:
        sma200 = df["close"].rolling(200, min_periods=50).mean()
        ret126 = df["close"].pct_change(126)
        vol20 = df["close"].pct_change().rolling(20).std()

        q25 = float(vol20.quantile(0.25))
        q75 = float(vol20.quantile(0.75))

        return {
            "bull": (df["close"] > sma200) & (ret126 > 0),
            "bear": (df["close"] < sma200) & (ret126 < 0),
            "high_vol": vol20 >= q75,
            "low_vol": vol20 <= q25,
        }

    @staticmethod
    def evaluate(
        y_true: np.ndarray,
        y_pred: np.ndarray,
        y_proba: np.ndarray,
        regime_masks: Dict[str, np.ndarray],
    ) -> Dict:
        out = {}
        y_true = np.asarray(y_true)
        y_pred = np.asarray(y_pred)
        y_proba = np.asarray(y_proba)

        for name, mask in regime_masks.items():
            m = np.asarray(mask, dtype=bool)
            if m.sum() < 30:
                out[name] = {"samples": int(m.sum()), "status": "insufficient_samples"}
                continue
            yt = y_true[m]
            yp = y_pred[m]
            ypba = y_proba[m]
            out[name] = {
                "samples": int(m.sum()),
                "accuracy": float(accuracy_score(yt, yp)),
                "precision": float(precision_score(yt, yp, zero_division=0)),
                "recall": float(recall_score(yt, yp, zero_division=0)),
                "f1": float(f1_score(yt, yp, zero_division=0)),
                "roc_auc": (
                    float(roc_auc_score(yt, ypba)) if len(np.unique(yt)) > 1 else 0.5
                ),
            }

        return out
