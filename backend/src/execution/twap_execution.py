"""TWAP execution scheduler."""

from __future__ import annotations

from typing import Dict, List


class TWAPExecution:
    def create_schedule(
        self, quantity: float, slices: int, interval_seconds: int
    ) -> Dict:
        slices = max(1, int(slices))
        child_qty = quantity / slices
        schedule: List[Dict] = []
        for i in range(slices):
            schedule.append(
                {"slice": i + 1, "qty": child_qty, "eta_sec": i * interval_seconds}
            )
        return {"algo": "TWAP", "slices": slices, "schedule": schedule}
