"""Model/data drift detector using distribution and performance shifts."""

from __future__ import annotations

from typing import Dict

import numpy as np


class DriftDetector:
    """Simple production drift detector for feature and score drift."""

    def __init__(self, psi_threshold: float = 0.2, perf_drop_threshold: float = 0.08):
        self.psi_threshold = psi_threshold
        self.perf_drop_threshold = perf_drop_threshold

    @staticmethod
    def _psi(expected: np.ndarray, actual: np.ndarray, bins: int = 10) -> float:
        expected = np.asarray(expected, dtype=float)
        actual = np.asarray(actual, dtype=float)
        if expected.size < 20 or actual.size < 20:
            return 0.0

        cuts = np.quantile(expected, np.linspace(0, 1, bins + 1))
        cuts[0] = -np.inf
        cuts[-1] = np.inf

        e_hist, _ = np.histogram(expected, bins=cuts)
        a_hist, _ = np.histogram(actual, bins=cuts)

        e_pct = np.clip(e_hist / max(e_hist.sum(), 1), 1e-6, None)
        a_pct = np.clip(a_hist / max(a_hist.sum(), 1), 1e-6, None)

        return float(np.sum((a_pct - e_pct) * np.log(a_pct / e_pct)))

    def evaluate(
        self,
        baseline_scores: np.ndarray,
        current_scores: np.ndarray,
        baseline_metric: float | None = None,
        current_metric: float | None = None,
    ) -> Dict:
        psi = self._psi(baseline_scores, current_scores)

        perf_drop = 0.0
        if baseline_metric is not None and current_metric is not None:
            perf_drop = float(baseline_metric - current_metric)

        drift_flags = {
            "score_distribution_drift": psi >= self.psi_threshold,
            "performance_drift": perf_drop >= self.perf_drop_threshold,
        }

        return {
            "psi": psi,
            "perf_drop": perf_drop,
            "thresholds": {
                "psi": self.psi_threshold,
                "perf_drop": self.perf_drop_threshold,
            },
            "drift_flags": drift_flags,
            "drift_detected": bool(any(drift_flags.values())),
        }
