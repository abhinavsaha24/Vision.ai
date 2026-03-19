"""Liquidity filters for execution eligibility."""

from __future__ import annotations

from typing import Dict


class LiquidityFilter:
    def __init__(self, min_adv: float = 1000000.0, max_spread_bps: float = 40.0):
        self.min_adv = min_adv
        self.max_spread_bps = max_spread_bps

    def evaluate(self, adv: float, spread_bps: float) -> Dict:
        eligible = adv >= self.min_adv and spread_bps <= self.max_spread_bps
        return {
            "eligible": eligible,
            "adv": adv,
            "spread_bps": spread_bps,
            "limits": {"min_adv": self.min_adv, "max_spread_bps": self.max_spread_bps},
        }
