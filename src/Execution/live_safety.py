"""
Live trading safety: pre-flight checks before enabling real money execution.

All checks must pass before the first live order is allowed.
This module is the gatekeeper between paper and live trading.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SafetyCheckResult:
    """Result of a single safety check."""
    name: str
    passed: bool
    message: str


@dataclass
class PreFlightReport:
    """Aggregated pre-flight check results."""
    all_passed: bool
    checks: List[SafetyCheckResult] = field(default_factory=list)
    blocked_reasons: List[str] = field(default_factory=list)


class LiveTradingSafety:
    """
    Pre-flight checklist for live trading.

    Must verify:
      1. Live trading is explicitly enabled in config
      2. API key is present and valid
      3. Risk limits are configured
      4. Kill switch is operational (not already tripped)
      5. Maximum position size is capped
      6. Exchange connectivity is confirmed
    """

    def __init__(self, settings, risk_manager, adapter=None):
        """
        Args:
            settings: Application settings object
            risk_manager: RiskManager instance
            adapter: ExchangeAdapter (BinanceAdapter for live)
        """
        self.settings = settings
        self.risk_manager = risk_manager
        self.adapter = adapter

    def run_preflight(self) -> PreFlightReport:
        """
        Run all pre-flight checks.

        Returns PreFlightReport with pass/fail status for each check.
        """
        checks = []

        # 1. Live trading explicitly enabled
        checks.append(self._check_live_enabled())

        # 2. API keys present
        checks.append(self._check_api_keys())

        # 3. Risk limits configured
        checks.append(self._check_risk_limits())

        # 4. Kill switch not already active
        checks.append(self._check_kill_switch())

        # 5. Position size capped
        checks.append(self._check_position_cap())

        # 6. Exchange connectivity
        checks.append(self._check_exchange_connectivity())

        all_passed = all(c.passed for c in checks)
        blocked = [c.message for c in checks if not c.passed]

        report = PreFlightReport(
            all_passed=all_passed,
            checks=checks,
            blocked_reasons=blocked,
        )

        if all_passed:
            logger.info("✅ Live trading pre-flight: ALL CHECKS PASSED")
        else:
            logger.warning(
                f"❌ Live trading pre-flight BLOCKED: "
                f"{len(blocked)} check(s) failed — {blocked}"
            )

        return report

    # --------------------------------------------------
    # Individual checks
    # --------------------------------------------------

    def _check_live_enabled(self) -> SafetyCheckResult:
        enabled = getattr(self.settings, "live_trading_enabled", False)
        mode = getattr(self.settings, "trading_mode", "paper")

        if not enabled or mode != "live":
            return SafetyCheckResult(
                name="live_trading_enabled",
                passed=False,
                message=(
                    "Live trading is not enabled. "
                    "Set LIVE_TRADING_ENABLED=true and TRADING_MODE=live in .env"
                ),
            )

        return SafetyCheckResult(
            name="live_trading_enabled",
            passed=True,
            message="Live trading is enabled",
        )

    def _check_api_keys(self) -> SafetyCheckResult:
        key = getattr(self.settings, "binance_api_key", None)
        secret = getattr(self.settings, "binance_secret", None)

        if not key or not secret or key == "optional_binance_key":
            return SafetyCheckResult(
                name="api_keys",
                passed=False,
                message="Binance API key and secret are required for live trading",
            )

        return SafetyCheckResult(
            name="api_keys",
            passed=True,
            message="API keys are configured",
        )

    def _check_risk_limits(self) -> SafetyCheckResult:
        limits = self.risk_manager.limits

        if limits.max_daily_loss <= 0 or limits.max_drawdown <= 0:
            return SafetyCheckResult(
                name="risk_limits",
                passed=False,
                message="Risk limits (max_daily_loss, max_drawdown) must be positive",
            )

        if limits.max_daily_loss > 0.10:
            return SafetyCheckResult(
                name="risk_limits",
                passed=False,
                message=f"Daily loss limit too high: {limits.max_daily_loss:.0%} (max allowed: 10%)",
            )

        return SafetyCheckResult(
            name="risk_limits",
            passed=True,
            message=f"Risk limits OK: daily_loss={limits.max_daily_loss:.1%}, drawdown={limits.max_drawdown:.1%}",
        )

    def _check_kill_switch(self) -> SafetyCheckResult:
        if self.risk_manager.kill_switch_active:
            return SafetyCheckResult(
                name="kill_switch",
                passed=False,
                message="Kill switch is currently ACTIVE — deactivate before enabling live trading",
            )

        return SafetyCheckResult(
            name="kill_switch",
            passed=True,
            message="Kill switch is inactive (ready)",
        )

    def _check_position_cap(self) -> SafetyCheckResult:
        max_pos = getattr(self.settings, "live_max_position_usd", 100.0)

        if max_pos <= 0:
            return SafetyCheckResult(
                name="position_cap",
                passed=False,
                message="LIVE_MAX_POSITION_USD must be a positive value",
            )

        if max_pos > 10000:
            return SafetyCheckResult(
                name="position_cap",
                passed=False,
                message=f"Position cap ${max_pos:.0f} is dangerously high for initial live testing",
            )

        return SafetyCheckResult(
            name="position_cap",
            passed=True,
            message=f"Max position cap: ${max_pos:.2f}",
        )

    def _check_exchange_connectivity(self) -> SafetyCheckResult:
        if self.adapter is None:
            return SafetyCheckResult(
                name="exchange_connectivity",
                passed=False,
                message="No exchange adapter configured",
            )

        try:
            balance = self.adapter.get_balance()
            usdt = balance.total.get("USDT", 0)

            return SafetyCheckResult(
                name="exchange_connectivity",
                passed=True,
                message=f"Exchange connected, USDT balance: {usdt:.2f}",
            )

        except Exception as e:
            return SafetyCheckResult(
                name="exchange_connectivity",
                passed=False,
                message=f"Exchange connection failed: {e}",
            )

    # --------------------------------------------------
    # Convenience
    # --------------------------------------------------

    def is_live_allowed(self) -> bool:
        """Quick check: is live trading allowed?"""
        return self.run_preflight().all_passed

    def get_report_dict(self) -> Dict:
        """Return pre-flight report as serializable dict."""
        report = self.run_preflight()
        return {
            "all_passed": report.all_passed,
            "checks": [
                {"name": c.name, "passed": c.passed, "message": c.message}
                for c in report.checks
            ],
            "blocked_reasons": report.blocked_reasons,
        }
