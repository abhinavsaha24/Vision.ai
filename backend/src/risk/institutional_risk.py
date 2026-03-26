"""Institutional risk aggregation and policy checks."""

from __future__ import annotations

from typing import Dict


class InstitutionalRiskEngine:
    """Aggregates market/model/liquidity risks into a unified score."""

    def evaluate(self, risk_state: Dict) -> Dict:
        market = float(risk_state.get("market_risk", 0.0))
        liquidity = float(risk_state.get("liquidity_risk", 0.0))
        model = float(risk_state.get("model_risk", 0.0))
        leverage = float(risk_state.get("leverage_risk", 0.0))

        total = 0.35 * market + 0.25 * liquidity + 0.25 * model + 0.15 * leverage
        risk_bucket = "low" if total < 0.33 else "medium" if total < 0.66 else "high"

        return {
            "aggregate_risk": round(total, 4),
            "risk_bucket": risk_bucket,
            "components": {
                "market_risk": market,
                "liquidity_risk": liquidity,
                "model_risk": model,
                "leverage_risk": leverage,
            },
            "policy_ok": risk_bucket != "high",
        }
