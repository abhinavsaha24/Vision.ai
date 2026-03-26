"""Institutional ensemble predictor with calibration-aware voting."""

from __future__ import annotations

from typing import Dict, List

import numpy as np


class EnsemblePredictor:
    """Combines heterogeneous model probabilities via weighted blending."""

    def __init__(self, weights: Dict[str, float] | None = None):
        self.weights = weights or {"rf": 0.35, "xgb": 0.35, "lgb": 0.2, "lstm": 0.1}

    def predict_proba(self, proba_map: Dict[str, np.ndarray]) -> np.ndarray:
        if not proba_map:
            return np.array([])

        valid: List[np.ndarray] = []
        used_weights: List[float] = []
        for name, w in self.weights.items():
            if (
                name in proba_map
                and proba_map[name] is not None
                and len(proba_map[name]) > 0
            ):
                arr = np.asarray(proba_map[name], dtype=float)
                valid.append(arr)
                used_weights.append(float(w))

        if not valid:
            first = next(iter(proba_map.values()))
            return np.asarray(first, dtype=float)

        weight_sum = sum(used_weights)
        norm = [w / weight_sum for w in used_weights]
        blended = np.zeros_like(valid[0], dtype=float)
        for arr, w in zip(valid, norm):
            blended += arr * w
        return np.clip(blended, 0.0, 1.0)

    def predict(
        self, proba_map: Dict[str, np.ndarray], threshold: float = 0.5
    ) -> np.ndarray:
        p = self.predict_proba(proba_map)
        if p.size == 0:
            return p
        return (p >= threshold).astype(int)
