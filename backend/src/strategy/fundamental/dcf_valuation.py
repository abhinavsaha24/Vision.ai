from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DCFInputs:
    revenue: float
    fcf_margin: float
    growth_5y: float
    discount_rate: float
    terminal_growth: float
    net_debt: float
    shares_outstanding: float


class DCFValuationEngine:
    """Five-year DCF model with Gordon-growth terminal value."""

    def value(self, i: DCFInputs) -> dict[str, float]:
        if i.shares_outstanding <= 0:
            raise ValueError("shares_outstanding must be > 0")
        if i.discount_rate <= i.terminal_growth:
            raise ValueError("discount_rate must be greater than terminal_growth")

        projected_fcfs = []
        revenue = i.revenue
        for _year in range(1, 6):
            revenue *= 1.0 + i.growth_5y
            projected_fcfs.append(revenue * i.fcf_margin)

        pv_fcf = 0.0
        for idx, fcf in enumerate(projected_fcfs, start=1):
            pv_fcf += fcf / ((1.0 + i.discount_rate) ** idx)

        terminal_fcf = projected_fcfs[-1] * (1.0 + i.terminal_growth)
        terminal_value = terminal_fcf / (i.discount_rate - i.terminal_growth)
        pv_terminal = terminal_value / ((1.0 + i.discount_rate) ** 5)

        enterprise_value = pv_fcf + pv_terminal
        equity_value = enterprise_value - i.net_debt
        fair_value_per_share = equity_value / i.shares_outstanding

        return {
            "enterprise_value": round(enterprise_value, 2),
            "equity_value": round(equity_value, 2),
            "fair_value_per_share": round(fair_value_per_share, 4),
            "pv_fcf": round(pv_fcf, 2),
            "pv_terminal": round(pv_terminal, 2),
        }

    def sensitivity(self, i: DCFInputs, growth_shift: float, discount_shift: float) -> dict[str, float]:
        shifted = DCFInputs(
            revenue=i.revenue,
            fcf_margin=i.fcf_margin,
            growth_5y=i.growth_5y + growth_shift,
            discount_rate=i.discount_rate + discount_shift,
            terminal_growth=i.terminal_growth,
            net_debt=i.net_debt,
            shares_outstanding=i.shares_outstanding,
        )
        return self.value(shifted)
