from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RiskCheckResult:
    approved: bool
    reason: str = ""


class RiskPolicy:
    def __init__(
        self,
        max_position_size: float,
        max_notional_exposure: float,
        max_drawdown_pct: float,
    ):
        self.max_position_size = max_position_size
        self.max_notional_exposure = max_notional_exposure
        self.max_drawdown_pct = max_drawdown_pct

    def evaluate(
        self,
        requested_qty: float,
        requested_notional: float,
        side: str,
        current_exposure: float,
        current_drawdown_pct: float,
    ) -> RiskCheckResult:
        if requested_qty < 0:
            return RiskCheckResult(False, "invalid_negative_quantity")
        if requested_qty > self.max_position_size:
            return RiskCheckResult(False, "max_position_size_exceeded")

        side_norm = str(side).strip().lower()
        if side_norm not in {"buy", "sell"}:
            return RiskCheckResult(False, "invalid_side")

        signed_notional = requested_notional if side_norm == "buy" else -requested_notional
        projected_exposure = current_exposure + signed_notional
        if abs(projected_exposure) > self.max_notional_exposure:
            return RiskCheckResult(False, "max_notional_exposure_exceeded")
        if current_drawdown_pct > self.max_drawdown_pct:
            return RiskCheckResult(False, "drawdown_limit_exceeded")
        return RiskCheckResult(True)
