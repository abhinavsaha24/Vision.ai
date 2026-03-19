"""System watchdog for heartbeat and stale component detection."""

from __future__ import annotations

import time
from typing import Dict


class SystemWatchdog:
    def __init__(self):
        self.heartbeats: Dict[str, float] = {}

    def beat(self, component: str):
        self.heartbeats[component] = time.time()

    def status(self, max_stale_seconds: float = 120.0) -> Dict:
        now = time.time()
        stale = [k for k, ts in self.heartbeats.items() if now - ts > max_stale_seconds]
        return {
            "tracked_components": len(self.heartbeats),
            "stale_components": stale,
            "healthy": len(stale) == 0,
        }
