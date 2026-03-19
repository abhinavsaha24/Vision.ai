"""VWAP execution allocator."""

from __future__ import annotations

from typing import Dict, List

import numpy as np


class VWAPExecution:
    def allocate(self, quantity: float, volume_curve: List[float]) -> Dict:
        if not volume_curve:
            volume_curve = [1.0]
        curve = np.asarray(volume_curve, dtype=float)
        curve = np.clip(curve, 0, None)
        total = float(curve.sum()) or 1.0
        weights = curve / total
        slices = [
            {"bucket": i + 1, "qty": float(quantity * w), "weight": float(w)}
            for i, w in enumerate(weights)
        ]
        return {"algo": "VWAP", "schedule": slices}
