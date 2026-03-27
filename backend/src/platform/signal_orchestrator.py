from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.src.strategy.fundamental.competitive_advantage import (
    CompetitiveAdvantageEngine,
    CompetitiveSnapshot,
)
from backend.src.strategy.fundamental.dcf_valuation import DCFInputs, DCFValuationEngine
from backend.src.strategy.fundamental.dividend import DividendSnapshot, DividendStrategyEngine
from backend.src.strategy.fundamental.earnings_intelligence import (
    EarningsIntelligenceEngine,
    EarningsSnapshot,
)
from backend.src.strategy.fundamental.equity_screening import EquityMetrics, EquityScreeningEngine
from backend.src.strategy.fundamental.macro_regime import MacroEngine, MacroSnapshot


@dataclass
class OrchestratorWeights:
    quant: float = 0.55
    fundamentals: float = 0.30
    macro: float = 0.15


class SignalOrchestrator:
    """Unifies quant, fundamental, and macro context into one trade decision score."""

    def __init__(self, weights: OrchestratorWeights | None = None):
        self.weights = weights or OrchestratorWeights()
        self.equity = EquityScreeningEngine()
        self.dcf = DCFValuationEngine()
        self.earnings = EarningsIntelligenceEngine()
        self.dividend = DividendStrategyEngine()
        self.moat = CompetitiveAdvantageEngine()
        self.macro = MacroEngine()

    def evaluate(self, market_tick: dict[str, Any], alpha_signal: dict[str, Any]) -> dict[str, Any]:
        eq = self.equity.score(
            EquityMetrics(
                pe_ratio=float(market_tick.get("pe_ratio", 18.0) or 18.0),
                revenue_growth_yoy=float(market_tick.get("revenue_growth_yoy", 0.08) or 0.08),
                debt_to_equity=float(market_tick.get("debt_to_equity", 0.8) or 0.8),
                gross_margin=float(market_tick.get("gross_margin", 0.42) or 0.42),
                roic=float(market_tick.get("roic", 0.11) or 0.11),
            )
        )

        dcf_result = self.dcf.value(
            DCFInputs(
                revenue=float(market_tick.get("revenue", 1_000_000_000.0) or 1_000_000_000.0),
                fcf_margin=float(market_tick.get("fcf_margin", 0.12) or 0.12),
                growth_5y=float(market_tick.get("growth_5y", 0.08) or 0.08),
                discount_rate=float(market_tick.get("wacc", 0.10) or 0.10),
                terminal_growth=float(market_tick.get("terminal_growth", 0.03) or 0.03),
                net_debt=float(market_tick.get("net_debt", 100_000_000.0) or 100_000_000.0),
                shares_outstanding=float(market_tick.get("shares_outstanding", 100_000_000.0) or 100_000_000.0),
            )
        )
        ref_price = float(alpha_signal.get("price", 0.0) or 0.0)
        dcf_upside = 0.0
        if ref_price > 0.0:
            dcf_upside = (float(dcf_result["fair_value_per_share"]) - ref_price) / ref_price
        dcf_score = max(0.0, min(1.0, 0.5 + dcf_upside))

        earnings = self.earnings.score(
            EarningsSnapshot(
                eps_estimate=float(market_tick.get("eps_estimate", 1.0) or 1.0),
                eps_actual=float(market_tick.get("eps_actual", 1.03) or 1.03),
                revenue_estimate=float(market_tick.get("revenue_estimate", 100.0) or 100.0),
                revenue_actual=float(market_tick.get("revenue_actual", 102.0) or 102.0),
                guidance_delta_pct=float(market_tick.get("guidance_delta_pct", 0.01) or 0.01),
            )
        )

        dividend = self.dividend.score(
            DividendSnapshot(
                dividend_yield=float(market_tick.get("dividend_yield", 0.02) or 0.02),
                payout_ratio=float(market_tick.get("payout_ratio", 0.45) or 0.45),
                dividend_cagr_5y=float(market_tick.get("dividend_cagr_5y", 0.05) or 0.05),
                free_cash_flow_coverage=float(market_tick.get("fcf_coverage", 1.6) or 1.6),
            )
        )

        moat = self.moat.score(
            CompetitiveSnapshot(
                gross_margin=float(market_tick.get("gross_margin", 0.42) or 0.42),
                operating_margin=float(market_tick.get("operating_margin", 0.16) or 0.16),
                market_share_trend=float(market_tick.get("market_share_trend", 0.01) or 0.01),
                switching_cost_index=float(market_tick.get("switching_cost_index", 0.55) or 0.55),
                network_effect_index=float(market_tick.get("network_effect_index", 0.5) or 0.5),
            )
        )

        macro = self.macro.score(
            MacroSnapshot(
                real_rate=float(market_tick.get("real_rate", 0.015) or 0.015),
                inflation_yoy=float(market_tick.get("inflation_yoy", 0.03) or 0.03),
                gdp_growth_yoy=float(market_tick.get("gdp_growth_yoy", 0.02) or 0.02),
                credit_spread=float(market_tick.get("credit_spread", 0.02) or 0.02),
                sector_momentum=float(market_tick.get("sector_momentum", 0.02) or 0.02),
            )
        )

        fundamentals_composite = (
            float(eq["composite"])
            + float(dcf_score)
            + float(earnings["composite"])
            + float(dividend["composite"])
            + float(moat["composite"])
        ) / 5.0

        quant_score = max(0.0, min(1.0, abs(float(alpha_signal.get("score", 0.0) or 0.0)) * float(alpha_signal.get("confidence", 0.0) or 0.0)))
        macro_score = float(macro["risk_on_score"])

        unified = (
            self.weights.quant * quant_score
            + self.weights.fundamentals * fundamentals_composite
            + self.weights.macro * macro_score
        )
        approved = bool(unified >= 0.55)

        return {
            "approved": approved,
            "unified_score": round(float(unified), 4),
            "quant_score": round(float(quant_score), 4),
            "fundamental_score": round(float(fundamentals_composite), 4),
            "macro_score": round(float(macro_score), 4),
            "components": {
                "equity_screening": eq,
                "dcf": {**dcf_result, "dcf_score": round(float(dcf_score), 4), "dcf_upside": round(float(dcf_upside), 4)},
                "earnings_intelligence": earnings,
                "dividend": dividend,
                "competitive_advantage": moat,
                "macro_regime": macro,
            },
        }
