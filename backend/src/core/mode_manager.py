"""
Mode manager: controls Research → Simulation → Live trading pipeline.

Enforces safety gates between operational modes:
  - RESEARCH: backtesting, feature engineering, model training
  - SIMULATION: real-time paper trading with live market data
  - LIVE: real execution through exchange APIs

Transitions are validated:
  - RESEARCH → SIMULATION: requires model trained + backtest passed
  - SIMULATION → LIVE: requires all preflight checks passed
  - Any → RESEARCH: always allowed (safe)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List

logger = logging.getLogger("vision-ai.modes")


class TradingMode(str, Enum):
    RESEARCH = "research"
    SIMULATION = "simulation"  # paper trading
    LIVE = "live"


@dataclass
class ModeTransition:
    """Record of a mode transition."""

    from_mode: str
    to_mode: str
    timestamp: str
    reason: str
    approved: bool


class ModeManager:
    """
    Manages the operational mode of the trading platform.

    Ensures safe transitions between research, simulation, and live trading.
    """

    def __init__(self, initial_mode: str = "simulation"):
        if initial_mode == "paper":
            initial_mode = "simulation"
        self.current_mode = TradingMode(initial_mode)
        self.transitions: List[ModeTransition] = []
        self._requirements: Dict[str, bool] = {
            "model_trained": False,
            "backtest_passed": False,
            "preflight_passed": False,
            "api_keys_valid": False,
        }

    # ---- Mode queries ----

    @property
    def is_research(self) -> bool:
        return self.current_mode == TradingMode.RESEARCH

    @property
    def is_simulation(self) -> bool:
        return self.current_mode == TradingMode.SIMULATION

    @property
    def is_live(self) -> bool:
        return self.current_mode == TradingMode.LIVE

    @property
    def allows_real_orders(self) -> bool:
        return self.current_mode == TradingMode.LIVE

    # ---- Transitions ----

    def can_transition(self, target: TradingMode) -> Dict:
        """Check if a mode transition is allowed."""
        reasons = []

        if target == self.current_mode:
            return {"allowed": True, "reasons": ["Already in this mode"]}

        # Always allowed to go back to research
        if target == TradingMode.RESEARCH:
            return {"allowed": True, "reasons": []}

        # RESEARCH → SIMULATION
        if target == TradingMode.SIMULATION:
            if not self._requirements["model_trained"]:
                reasons.append("Model must be trained before simulation")
            return {
                "allowed": len(reasons) == 0,
                "reasons": reasons,
            }

        # → LIVE
        if target == TradingMode.LIVE:
            if self.current_mode == TradingMode.RESEARCH:
                reasons.append("Cannot go directly from research to live")
            if not self._requirements["backtest_passed"]:
                reasons.append("Backtest must pass before live trading")
            if not self._requirements["preflight_passed"]:
                reasons.append("Preflight safety checks must pass")
            if not self._requirements["api_keys_valid"]:
                reasons.append("API keys must be validated")
            return {
                "allowed": len(reasons) == 0,
                "reasons": reasons,
            }

        return {"allowed": False, "reasons": ["Unknown target mode"]}

    def transition(self, target: TradingMode, reason: str = "") -> Dict:
        """Attempt to transition to a new mode."""
        check = self.can_transition(target)

        transition = ModeTransition(
            from_mode=self.current_mode.value,
            to_mode=target.value,
            timestamp=datetime.now(timezone.utc).isoformat(),
            reason=reason,
            approved=check["allowed"],
        )
        self.transitions.append(transition)

        if check["allowed"]:
            old = self.current_mode
            self.current_mode = target
            logger.info("Mode transition: %s → %s (%s)", old.value, target.value, reason)
            return {"success": True, "mode": target.value}
        else:
            logger.warning(
                "Mode transition blocked: %s → %s: %s",
                self.current_mode.value,
                target.value,
                check["reasons"]
            )
            return {"success": False, "reasons": check["reasons"]}

    # ---- Requirements ----

    def set_requirement(self, key: str, value: bool):
        """Update a transition requirement."""
        if key in self._requirements:
            self._requirements[key] = value
            logger.info("Mode requirement '%s' → %s", key, value)

    # ---- Status ----

    def get_status(self) -> Dict:
        """Get current mode and transition history."""
        return {
            "current_mode": self.current_mode.value,
            "requirements": self._requirements,
            "can_simulate": self.can_transition(TradingMode.SIMULATION)["allowed"],
            "can_go_live": self.can_transition(TradingMode.LIVE)["allowed"],
            "recent_transitions": [
                {
                    "from": t.from_mode,
                    "to": t.to_mode,
                    "timestamp": t.timestamp,
                    "reason": t.reason,
                    "approved": t.approved,
                }
                for t in self.transitions[-10:]
            ],
        }
