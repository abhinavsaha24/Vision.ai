"""Crash protection overlay for extreme market conditions."""

from __future__ import annotations

from typing import Dict


class CrashProtection:
    def __init__(
        self, crash_threshold: float = -0.08, vol_spike_threshold: float = 3.0
    ):
        self.crash_threshold = crash_threshold
        self.vol_spike_threshold = vol_spike_threshold

    def evaluate(self, market_state: Dict) -> Dict:
        ret_1d = float(market_state.get("return_1d", 0.0))
        vol_ratio = float(market_state.get("vol_ratio", 1.0))

        crash_flag = (
            ret_1d <= self.crash_threshold or vol_ratio >= self.vol_spike_threshold
        )
        mode = "capital_preservation" if crash_flag else "normal"
        max_position_scale = 0.25 if crash_flag else 1.0

        return {
            "crash_flag": crash_flag,
            "mode": mode,
            "max_position_scale": max_position_scale,
            "inputs": {"return_1d": ret_1d, "vol_ratio": vol_ratio},
        }
