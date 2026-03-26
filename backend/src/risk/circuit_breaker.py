"""Risk-level circuit breaker gates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class RiskCircuitConfig:
    max_drawdown_pct: float = 0.12
    max_daily_loss_pct: float = 0.04
    max_var_breach_count: int = 3


class RiskCircuitBreaker:
    def __init__(self, cfg: RiskCircuitConfig | None = None):
        self.cfg = cfg or RiskCircuitConfig()
        self.tripped = False
        self.reason = ""

    def evaluate(self, state: Dict) -> bool:
        if float(state.get("drawdown_pct", 0.0)) >= self.cfg.max_drawdown_pct:
            self._trip("drawdown_limit")
        elif float(state.get("daily_loss_pct", 0.0)) >= self.cfg.max_daily_loss_pct:
            self._trip("daily_loss_limit")
        elif int(state.get("var_breach_count", 0)) >= self.cfg.max_var_breach_count:
            self._trip("var_breach_limit")
        return self.tripped

    def _trip(self, reason: str):
        self.tripped = True
        self.reason = reason

    def reset(self):
        self.tripped = False
        self.reason = ""

    def status(self) -> Dict:
        return {"tripped": self.tripped, "reason": self.reason}
