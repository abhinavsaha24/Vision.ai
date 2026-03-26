from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RiskLimits:
    max_symbol_abs: float = 0.30
    max_net_abs: float = 0.35
    max_gross_abs: float = 1.20
    min_order_notional: float = 10.0


@dataclass
class RiskDecision:
    approved: bool
    reasons: list[str]
    approved_positions: dict[str, float]
    metrics: dict[str, float]


class RiskEngine:
    """Deterministic risk gate over allocator targets.

    This module performs no discovery and no execution; it only validates and clips
    desired exposures into a deployable risk-safe target set.
    """

    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()

    def evaluate(
        self,
        targets: dict[str, float],
        equity_usd: float,
        prices: dict[str, float],
    ) -> RiskDecision:
        reasons: list[str] = []
        clipped: dict[str, float] = {}

        for symbol, exposure in targets.items():
            e = float(exposure)
            clipped_e = max(-self.limits.max_symbol_abs, min(self.limits.max_symbol_abs, e))
            if clipped_e != e:
                reasons.append(f"symbol_clipped:{symbol}")
            clipped[symbol] = clipped_e

        net = sum(clipped.values())
        gross = sum(abs(v) for v in clipped.values())

        if abs(net) > self.limits.max_net_abs and clipped:
            scale = self.limits.max_net_abs / abs(net)
            clipped = {k: v * scale for k, v in clipped.items()}
            net = sum(clipped.values())
            gross = sum(abs(v) for v in clipped.values())
            reasons.append("net_exposure_scaled")

        if gross > self.limits.max_gross_abs and clipped:
            scale = self.limits.max_gross_abs / gross
            clipped = {k: v * scale for k, v in clipped.items()}
            net = sum(clipped.values())
            gross = sum(abs(v) for v in clipped.values())
            reasons.append("gross_exposure_scaled")

        approved_positions: dict[str, float] = {}
        for symbol, exposure in clipped.items():
            px = float(prices.get(symbol, 0.0) or 0.0)
            if px <= 0:
                reasons.append(f"missing_price:{symbol}")
                continue
            if float(equity_usd) <= 0.0:
                reasons.append(f"non_positive_equity:{symbol}")
                continue
            notional = abs(exposure) * float(equity_usd)
            if 0.0 < notional < self.limits.min_order_notional:
                reasons.append(f"below_min_notional:{symbol}")
                continue
            approved_positions[symbol] = exposure

        approved = len(approved_positions) > 0
        return RiskDecision(
            approved=approved,
            reasons=sorted(set(reasons)),
            approved_positions=approved_positions,
            metrics={
                "net_exposure": float(net),
                "gross_exposure": float(gross),
                "approved_count": float(len(approved_positions)),
            },
        )
