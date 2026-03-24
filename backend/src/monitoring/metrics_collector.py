"""Metrics collector for system KPIs and timeseries snapshots."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Deque, Dict


class MetricsCollector:
    def __init__(self, maxlen: int = 2000):
        self.snapshots: Deque[Dict] = deque(maxlen=maxlen)

    def push(self, payload: Dict):
        self.snapshots.append({"timestamp": datetime.now(timezone.utc).isoformat(), **payload})

    def latest(self) -> Dict:
        return self.snapshots[-1] if self.snapshots else {}

    def summary(self) -> Dict:
        return {
            "count": len(self.snapshots),
            "latest": self.latest(),
        }
