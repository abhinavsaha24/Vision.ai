"""Institutional slippage estimation model."""

from __future__ import annotations

from typing import Dict


class SlippageModel:
    def estimate_bps(
        self, order_size: float, adv: float, volatility: float, spread_bps: float
    ) -> float:
        participation = 0.0 if adv <= 0 else min(order_size / adv, 1.0)
        impact = 8.0 * participation**0.6
        vol_component = 50.0 * max(volatility, 0.0)
        spread_component = max(spread_bps, 0.0) * 0.5
        return float(impact + vol_component + spread_component)

    def report(
        self, order_size: float, adv: float, volatility: float, spread_bps: float
    ) -> Dict:
        bps = self.estimate_bps(order_size, adv, volatility, spread_bps)
        return {
            "estimated_slippage_bps": bps,
            "inputs": {
                "order_size": order_size,
                "adv": adv,
                "volatility": volatility,
                "spread_bps": spread_bps,
            },
        }
