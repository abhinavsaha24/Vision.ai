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
from dataclasses import dataclass
from datetime import timezone
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    """Risk management parameters."""

    max_position_size: float = 0.02  # 2% max risk per trade (strictly enforced)
    max_daily_loss: float = 0.03  # 3% daily loss limit
    max_drawdown: float = 0.10  # 10% absolute max drawdown kill-switch
    max_open_trades: int = 5  # increased from 3 for multi-symbol
    max_portfolio_exposure: float = 0.6  # 60% max portfolio exposure
    max_correlation: float = 0.65  # tighter correlation check
    
    # Dynamic Exit Parameters
    stop_loss_pct: float = 0.01  # Fast stop-loss target (~1%)
    sl_atr_multiplier: float = 1.0  # Phase 9: 1.0 ATR
    tp_rr_ratio: float = 3.5  # Base target in requested 3R-5R band
    trailing_stop_pct: float = 0.015  # Phase 9: Trailing stop of 1.5%
    
    target_daily_vol: float = 0.02  # 2% target daily volatility per position
    max_consecutive_losses: int = 5  # halt after 5 consecutive losses


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
        logger.critical("KILL SWITCH ACTIVATED: %s", reason)

    def deactivate_kill_switch(self):
        self.kill_switch_active = False
        self._log_event("KILL_SWITCH", "Deactivated", "info")

    # --------------------------------------------------
    # Position Sizing
    # --------------------------------------------------

    def calculate_position_size(
        self,
        capital: float,
        price: float,
        volatility: float = 0.0,
        confidence: float = 0.5,
        rolling_sharpe: float = 1.0,
        current_drawdown: float = 0.0,
    ) -> float:
        """
        Calculate volatility-targeted position size.

        Method: Target a fixed daily volatility per position.
        Size = (target_vol * capital) / (realized_vol * price)

        Capital Scaling:
        IF Sharpe > 1.5: Increase capital allocation limit securely.
        IF Sharpe < 1.0: Defensively scale down capital allocation.
        
        Phase 6 Drawdown Control:
        IF Drawdown > 0.15: Pause entirely (size = 0)
        IF Drawdown > 0.10: Halve effective capital
        """
        if capital <= 0 or price <= 0:
            return 0
            
        # Drawdown Control Engine (Phase 6)
        if current_drawdown > 0.15:
            self._log_event("DRAWDOWN_BREACH", f"DD {current_drawdown:.2%} > 15%. Halting sizes.", "critical")
            return 0.0
            
        # --- Capital Scaling Engine ---
        if rolling_sharpe > 1.5:
            # aggressive sizing when system is highly profitable
            effective_capital = capital * 1.5
            max_size_limit = self.limits.max_position_size * 1.5
        elif rolling_sharpe < 1.0:
            # defensive sizing when system is underperforming
            effective_capital = capital * 0.5
            max_size_limit = self.limits.max_position_size * 0.5
        else:
            effective_capital = capital
            max_size_limit = self.limits.max_position_size
            
        if current_drawdown > 0.10:
            # 50% cut if we are deep in drawdown
            effective_capital *= 0.5
            max_size_limit *= 0.5

        # Base position from volatility targeting
        if volatility > 0:
            # Target daily vol approach
            target_vol = self.limits.target_daily_vol
            vol_adjusted_size = (target_vol * effective_capital) / (volatility * price + 1e-8)
        else:
            # Fallback: fixed fraction
            vol_adjusted_size = (effective_capital * max_size_limit) / price

        # Confidence scaling
        # confidence is typically [0, 1] mapped from abs(proba - 0.5) * 2
        kelly_scale = max(0.5, min(1.0, confidence * 1.5))
        
        position_size = vol_adjusted_size * kelly_scale

        # Hard cap at scaled max_position_size
        max_size = (effective_capital * max_size_limit) / price
        position_size = min(position_size, max_size)

        return max(0.0, position_size)

    def confidence_size_multiplier(self, confidence: float) -> float:
        """Map confidence to institutional 2x/1x/0.5x sizing buckets."""
        if confidence >= 0.75:
            return 2.0
        if confidence >= 0.55:
            return 1.0
        return 0.5

    def dynamic_rr_target(self, confidence: float) -> float:
        """Map confidence to RR target in 3R..5R band."""
        if confidence >= 0.8:
            return 5.0
        if confidence >= 0.65:
            return 4.0
        return 3.0

    def calculate_stop_loss(
        self, entry_price: float, side: str = "long", atr: float = 0.0
    ) -> float:
        """Calculate stop loss price using ATR or fixed %."""
        if atr > 0:
            # ATR-based stop
            stop_distance = atr * self.limits.sl_atr_multiplier
        else:
            stop_distance = entry_price * self.limits.stop_loss_pct

        if side == "long":
            return entry_price - stop_distance
        else:
            return entry_price + stop_distance

    def calculate_trailing_stop(
        self, entry_price: float, extreme_price: float, side: str = "long"
    ) -> float:
        """Calculate trailing stop. extreme_price is highest for long, lowest for short."""
        trail = self.limits.trailing_stop_pct

        if side == "long":
            return extreme_price * (1 - trail)
        else:
            # For shorts, trail from the lowest price seen since entry
            return extreme_price * (1 + trail)

    def calculate_take_profit(
        self,
        entry_price: float,
        side: str = "long",
        stop_loss_price: float = 0.0,
        rr_ratio: Optional[float] = None,
    ) -> float:
        """Calculate take profit level based on Risk-Reward (RR) ratio."""
        rr = float(rr_ratio if rr_ratio is not None else self.limits.tp_rr_ratio)
        if stop_loss_price > 0:
            risk_distance = abs(entry_price - stop_loss_price)
            tp_distance = risk_distance * rr
        else:
            # Fallback to fixed percent converted to target RR
            tp_distance = entry_price * (self.limits.stop_loss_pct * rr)

        if side == "long":
            return entry_price + tp_distance
        else:
            return entry_price - tp_distance

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
        equity_curve = portfolio.get("equity_curve", [])
        capital = float(equity_curve[-1]) if equity_curve else portfolio.get("cash", 0)
        if capital <= 0:
            return False

        loss_ratio = abs(min(0, daily_pnl)) / capital
        if loss_ratio >= self.limits.max_daily_loss:
            self._log_event(
                "DAILY_LOSS_BREACH", f"Daily loss: {loss_ratio:.2%}", "critical"
            )
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

    def _check_liquidity_constraints(self, trade_context: Optional[Dict]) -> bool:
        if not trade_context:
            return True
        spread_bps = float(trade_context.get("spread_bps", 0.0) or 0.0)
        depth_usd = float(trade_context.get("book_depth_usd", 0.0) or 0.0)
        trade_value = float(trade_context.get("trade_value", 0.0) or 0.0)

        if spread_bps > 35.0:
            self._log_event(
                "LIQUIDITY_BREACH", f"Spread too wide: {spread_bps:.2f} bps", "critical"
            )
            return False

        if depth_usd > 0 and trade_value > depth_usd * 0.12:
            self._log_event(
                "LIQUIDITY_BREACH", "Trade too large for visible depth", "warning"
            )
            return False
        return True

    def _check_correlation_constraints(
        self, portfolio: Dict, symbol: str, trade_context: Optional[Dict]
    ) -> bool:
        if not trade_context:
            return True

        correlations = trade_context.get("correlations") or {}
        positions = portfolio.get("positions", {}) or {}
        if not positions:
            return True

        max_corr = 0.0
        for held_symbol in positions:
            if held_symbol == symbol:
                continue
            corr = abs(float(correlations.get(held_symbol, 0.0) or 0.0))
            max_corr = max(max_corr, corr)

        if max_corr > self.limits.max_correlation:
            self._log_event(
                "CORRELATION_BREACH",
                f"{symbol} exceeds max correlation: {max_corr:.2f} > {self.limits.max_correlation:.2f}",
                "critical",
            )
            return False
        return True

    def _dynamic_size_multiplier(
        self, volatility: float, trade_context: Optional[Dict]
    ) -> float:
        multiplier = 1.0
        if volatility > 0:
            multiplier *= min(1.0, 0.03 / max(volatility, 1e-6))

        if trade_context:
            spread_bps = float(trade_context.get("spread_bps", 0.0) or 0.0)
            imbalance = abs(
                float(trade_context.get("order_book_imbalance", 0.0) or 0.0)
            )

            spread_factor = max(0.3, 1.0 - (spread_bps / 60.0))
            imbalance_factor = 1.0 + min(0.15, imbalance * 0.2)
            multiplier *= spread_factor * imbalance_factor

        return max(0.2, min(1.0, multiplier))

    # --------------------------------------------------
    # Trade Approval
    # --------------------------------------------------

    def approve_trade(
        self,
        portfolio: Dict,
        trade_value: float,
        volatility: float = 0.0,
        symbol: str = "",
        trade_context: Optional[Dict] = None,
    ) -> Dict:
        """
        Multi-layer trade approval.

        Returns:
            {"approved": bool, "reason": str, "adjustments": dict}
        """
        if self.kill_switch_active:
            return {
                "approved": False,
                "reason": "Kill switch active",
                "adjustments": {},
            }

        checks = [
            ("position_size", self.check_position_size(portfolio, trade_value)),
            ("drawdown", self.check_drawdown(portfolio)),
            ("daily_loss", self.check_daily_loss(portfolio)),
            ("open_trades", self.check_open_trades(portfolio)),
            ("portfolio_exposure", self.check_portfolio_exposure(portfolio)),
            (
                "liquidity",
                self._check_liquidity_constraints(
                    {**(trade_context or {}), "trade_value": trade_value}
                ),
            ),
            (
                "correlation",
                self._check_correlation_constraints(portfolio, symbol, trade_context),
            ),
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

        dynamic_mult = self._dynamic_size_multiplier(volatility, trade_context)
        if dynamic_mult < 0.99:
            adjustments["reduce_size"] = round(
                min(adjustments.get("reduce_size", 1.0), dynamic_mult), 4
            )
            self._log_event(
                "SIZE_ADJUSTMENT",
                f"Dynamic size multiplier: {dynamic_mult:.2f}",
                "info",
            )

        return {
            "approved": True,
            "reason": "All checks passed",
            "adjustments": adjustments,
        }

    # --------------------------------------------------
    # VaR Estimation
    # --------------------------------------------------

    def estimate_var(
        self, returns: np.ndarray, confidence: float = 0.95, capital: float = 100000
    ) -> Dict:
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
        cvar_pct = (
            float(sorted_returns[: var_idx + 1].mean()) if var_idx > 0 else var_pct
        )

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
        if (
            risk_factors.get("volatility") == "high"
            or risk_factors.get("drawdown", 0) > 0.1
        ):
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
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self.events.append(event)
        if len(self.events) > 1000:
            self.events = self.events[-500:]

    def get_events(self, limit: int = 50) -> List[Dict]:
        return [
            {
                "type": e.event_type,
                "message": e.message,
                "severity": e.severity,
                "time": e.timestamp,
            }
            for e in self.events[-limit:]
        ]
