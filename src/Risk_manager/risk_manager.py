"""
Professional risk management system.

Features:
  - Position size limits
  - Drawdown controls
  - Daily loss limits
  - Volatility-adjusted exposure
  - Trailing stops
  - Global kill switch
  - Value at Risk (VaR) estimation
"""

from __future__ import annotations

import logging
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    """Risk management parameters."""
    max_position_size: float = 0.05       # 5% of capital per trade
    max_daily_loss: float = 0.05          # 5% daily loss limit
    max_drawdown: float = 0.20            # 20% max drawdown
    max_open_trades: int = 5
    max_portfolio_exposure: float = 0.8   # 80% max portfolio exposure
    max_correlation: float = 0.8          # max correlation between positions
    stop_loss_pct: float = 0.02           # 2% stop loss
    trailing_stop_pct: float = 0.03       # 3% trailing stop
    take_profit_pct: float = 0.05         # 5% take profit


@dataclass
class RiskEvent:
    """Logged risk event."""
    event_type: str
    message: str
    severity: str  # "info", "warning", "critical"
    timestamp: str = ""


class RiskManager:
    """
    Professional risk management with multi-layer controls.
    """

    def __init__(self, limits: RiskLimits = RiskLimits()):
        self.limits = limits
        self.kill_switch_active = False
        self.events: List[RiskEvent] = []

    # --------------------------------------------------
    # Kill Switch
    # --------------------------------------------------

    def activate_kill_switch(self, reason: str = "Manual"):
        """Halt all trading immediately."""
        self.kill_switch_active = True
        self._log_event("KILL_SWITCH", f"Activated: {reason}", "critical")
        logger.critical(f"KILL SWITCH ACTIVATED: {reason}")

    def deactivate_kill_switch(self):
        self.kill_switch_active = False
        self._log_event("KILL_SWITCH", "Deactivated", "info")

    # --------------------------------------------------
    # Position Sizing
    # --------------------------------------------------

    def calculate_position_size(self, capital: float, price: float,
                                volatility: float = 0.0) -> float:
        """Calculate risk-adjusted position size."""
        if capital <= 0 or price <= 0:
            return 0

        base_risk = capital * self.limits.max_position_size

        # Volatility adjustment: reduce size in high vol
        if volatility > 0:
            vol_factor = min(1.0, 0.02 / (volatility + 1e-8))
            base_risk *= vol_factor

        return base_risk / price

    def calculate_stop_loss(self, entry_price: float, side: str = "long",
                            atr: float = 0.0) -> float:
        """Calculate stop loss price using ATR or fixed %."""
        if atr > 0:
            # ATR-based stop: 2x ATR
            stop_distance = atr * 2
        else:
            stop_distance = entry_price * self.limits.stop_loss_pct

        if side == "long":
            return entry_price - stop_distance
        else:
            return entry_price + stop_distance

    def calculate_trailing_stop(self, entry_price: float, highest_price: float,
                                side: str = "long") -> float:
        """Calculate trailing stop based on highest price seen."""
        trail = self.limits.trailing_stop_pct

        if side == "long":
            return highest_price * (1 - trail)
        else:
            return highest_price * (1 + trail)  # for short, trail from lowest

    def calculate_take_profit(self, entry_price: float, side: str = "long") -> float:
        """Calculate take profit level."""
        tp = self.limits.take_profit_pct

        if side == "long":
            return entry_price * (1 + tp)
        else:
            return entry_price * (1 - tp)

    # --------------------------------------------------
    # Risk Checks
    # --------------------------------------------------

    def check_position_size(self, portfolio: Dict, trade_value: float) -> bool:
        capital = portfolio.get("cash", 0)
        if capital <= 0:
            return False
        return (trade_value / capital) <= self.limits.max_position_size

    def check_drawdown(self, portfolio: Dict) -> bool:
        equity = portfolio.get("equity_curve", [])
        if len(equity) < 2:
            return True

        peak = max(equity)
        if peak == 0:
            return True

        current = equity[-1]
        drawdown = (peak - current) / peak

        if drawdown >= self.limits.max_drawdown:
            self._log_event("DRAWDOWN_BREACH", f"Drawdown: {drawdown:.2%}", "critical")
            return False

        return True

    def check_daily_loss(self, portfolio: Dict) -> bool:
        daily_pnl = portfolio.get("daily_pnl", 0)
        capital = portfolio.get("cash", 0)
        if capital <= 0:
            return False

        loss_ratio = abs(min(0, daily_pnl)) / capital
        if loss_ratio >= self.limits.max_daily_loss:
            self._log_event("DAILY_LOSS_BREACH", f"Daily loss: {loss_ratio:.2%}", "critical")
            return False
        return True

    def check_open_trades(self, portfolio: Dict) -> bool:
        return portfolio.get("open_trades", 0) < self.limits.max_open_trades

    def check_portfolio_exposure(self, portfolio: Dict) -> bool:
        """Check total portfolio exposure doesn't exceed limit."""
        cash = portfolio.get("cash", 0)
        equity = portfolio.get("equity_curve", [cash])
        total_equity = equity[-1] if equity else cash

        positions = portfolio.get("positions", {})
        total_exposure = sum(
            pos.get("quantity", 0) * pos.get("entry_price", 0)
            for pos in positions.values()
        )

        if total_equity <= 0:
            return False

        exposure_ratio = total_exposure / total_equity
        return exposure_ratio <= self.limits.max_portfolio_exposure

    # --------------------------------------------------
    # Trade Approval
    # --------------------------------------------------

    def approve_trade(self, portfolio: Dict, trade_value: float,
                      volatility: float = 0.0) -> Dict:
        """
        Multi-layer trade approval.

        Returns:
            {"approved": bool, "reason": str, "adjustments": dict}
        """
        if self.kill_switch_active:
            return {"approved": False, "reason": "Kill switch active", "adjustments": {}}

        checks = [
            ("position_size", self.check_position_size(portfolio, trade_value)),
            ("drawdown", self.check_drawdown(portfolio)),
            ("daily_loss", self.check_daily_loss(portfolio)),
            ("open_trades", self.check_open_trades(portfolio)),
            ("portfolio_exposure", self.check_portfolio_exposure(portfolio)),
        ]

        for name, passed in checks:
            if not passed:
                return {
                    "approved": False,
                    "reason": f"Failed: {name}",
                    "adjustments": {},
                }

        # Suggest adjustments based on volatility
        adjustments = {}
        if volatility > 0.05:
            adjustments["reduce_size"] = 0.5  # halve position in high vol
            self._log_event("VOL_ADJUSTMENT", f"High vol: {volatility:.4f}", "warning")

        return {"approved": True, "reason": "All checks passed", "adjustments": adjustments}

    # --------------------------------------------------
    # VaR Estimation
    # --------------------------------------------------

    def estimate_var(self, returns: np.ndarray, confidence: float = 0.95,
                     capital: float = 100000) -> Dict:
        """
        Estimate Value at Risk.

        Args:
            returns: array of historical returns
            confidence: confidence level (0.95 = 95%)
            capital: portfolio value

        Returns:
            {"var_pct": float, "var_amount": float, "cvar_pct": float}
        """
        if len(returns) < 30:
            return {"var_pct": 0, "var_amount": 0, "cvar_pct": 0}

        sorted_returns = np.sort(returns)
        var_idx = int((1 - confidence) * len(sorted_returns))

        var_pct = float(sorted_returns[var_idx])
        cvar_pct = float(sorted_returns[:var_idx + 1].mean()) if var_idx > 0 else var_pct

        return {
            "var_pct": round(abs(var_pct), 6),
            "var_amount": round(abs(var_pct) * capital, 2),
            "cvar_pct": round(abs(cvar_pct), 6),
            "cvar_amount": round(abs(cvar_pct) * capital, 2),
        }

    # --------------------------------------------------
    # Risk Score
    # --------------------------------------------------

    def calculate_risk(self, df) -> Dict:
        """Calculate composite risk score from market data."""
        risk_factors = {}

        # Volatility risk
        if "volatility_20" in df.columns:
            vol = df["volatility_20"].iloc[-1]
            vol_median = df["volatility_20"].median()
            risk_factors["volatility"] = "high" if vol > vol_median * 1.5 else "normal"
        else:
            risk_factors["volatility"] = "unknown"

        # Drawdown risk
        if "close" in df.columns and len(df) > 20:
            peak = df["close"].iloc[-20:].max()
            current = df["close"].iloc[-1]
            dd = (peak - current) / peak if peak > 0 else 0
            risk_factors["drawdown"] = round(float(dd), 4)
        else:
            risk_factors["drawdown"] = 0

        # Overall risk level
        if risk_factors.get("volatility") == "high" or risk_factors.get("drawdown", 0) > 0.1:
            risk_level = "high"
        elif risk_factors.get("drawdown", 0) > 0.05:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "risk_level": risk_level,
            "factors": risk_factors,
            "kill_switch": self.kill_switch_active,
        }

    # --------------------------------------------------
    # Event Logging
    # --------------------------------------------------

    def _log_event(self, event_type: str, message: str, severity: str):
        from datetime import datetime
        event = RiskEvent(
            event_type=event_type,
            message=message,
            severity=severity,
            timestamp=datetime.utcnow().isoformat(),
        )
        self.events.append(event)
        if len(self.events) > 1000:
            self.events = self.events[-500:]

    def get_events(self, limit: int = 50) -> List[Dict]:
        return [
            {"type": e.event_type, "message": e.message,
             "severity": e.severity, "time": e.timestamp}
            for e in self.events[-limit:]
        ]