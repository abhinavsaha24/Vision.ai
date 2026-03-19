"""
Execution circuit breakers for live trading safety.

These guardrails are designed to stop new entries when market data,
execution quality, or runtime reliability degrades beyond safe limits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple


@dataclass
class CircuitBreakerConfig:
    """Thresholds for execution safety checks."""

    max_consecutive_failures: int = 3
    max_data_staleness_seconds: int = 120
    max_latency_ms: float = 1500.0
    max_slippage_pct: float = 0.005  # 50 bps


@dataclass
class CircuitBreakerState:
    """Mutable execution safety state."""

    tripped: bool = False
    trip_reason: str = ""
    consecutive_failures: int = 0
    last_data_age_seconds: float = 0.0
    last_latency_ms: float = 0.0
    last_slippage_pct: float = 0.0
    last_updated: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ExecutionCircuitBreaker:
    """Tracks execution safety and trips on repeated or severe breaches."""

    def __init__(self, config: Optional[CircuitBreakerConfig] = None):
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitBreakerState()

    def evaluate_data_freshness(
        self, market_timestamp: Optional[datetime]
    ) -> Tuple[bool, str]:
        """Validate the market data age against staleness threshold."""
        if market_timestamp is None:
            return True, "no_timestamp"

        now = datetime.now(timezone.utc)
        if market_timestamp.tzinfo is None:
            market_timestamp = market_timestamp.replace(tzinfo=timezone.utc)

        age = max((now - market_timestamp).total_seconds(), 0.0)
        self.state.last_data_age_seconds = age
        self.state.last_updated = now.isoformat()

        if age > self.config.max_data_staleness_seconds:
            self.trip(f"data_staleness:{age:.1f}s")
            return False, "stale_market_data"

        return True, "ok"

    def evaluate_execution_quality(
        self, latency_ms: float, slippage_pct: float
    ) -> Tuple[bool, str]:
        """Validate execution latency and slippage."""
        self.state.last_latency_ms = max(latency_ms, 0.0)
        self.state.last_slippage_pct = max(slippage_pct, 0.0)
        self.state.last_updated = datetime.now(timezone.utc).isoformat()

        if self.state.last_latency_ms > self.config.max_latency_ms:
            self.trip(f"latency_breach:{self.state.last_latency_ms:.1f}ms")
            return False, "latency_breach"

        if self.state.last_slippage_pct > self.config.max_slippage_pct:
            self.trip(f"slippage_breach:{self.state.last_slippage_pct:.4%}")
            return False, "slippage_breach"

        return True, "ok"

    def record_failure(self, reason: str = "execution_failure") -> bool:
        """Increment failure counter and trip if threshold is exceeded."""
        self.state.consecutive_failures += 1
        self.state.last_updated = datetime.now(timezone.utc).isoformat()

        if self.state.consecutive_failures >= self.config.max_consecutive_failures:
            self.trip(f"{reason}:consecutive={self.state.consecutive_failures}")
            return True
        return False

    def record_success(self):
        """Reset consecutive failures after a successful cycle."""
        self.state.consecutive_failures = 0
        self.state.last_updated = datetime.now(timezone.utc).isoformat()

    def trip(self, reason: str):
        """Trip breaker and store reason."""
        self.state.tripped = True
        self.state.trip_reason = reason
        self.state.last_updated = datetime.now(timezone.utc).isoformat()

    def reset(self):
        """Manual reset for operational recovery workflows."""
        self.state = CircuitBreakerState()

    def get_status(self) -> Dict:
        """Serializable breaker state for APIs and monitoring."""
        return {
            "tripped": self.state.tripped,
            "trip_reason": self.state.trip_reason,
            "consecutive_failures": self.state.consecutive_failures,
            "last_data_age_seconds": round(self.state.last_data_age_seconds, 3),
            "last_latency_ms": round(self.state.last_latency_ms, 3),
            "last_slippage_pct": round(self.state.last_slippage_pct, 6),
            "thresholds": {
                "max_consecutive_failures": self.config.max_consecutive_failures,
                "max_data_staleness_seconds": self.config.max_data_staleness_seconds,
                "max_latency_ms": self.config.max_latency_ms,
                "max_slippage_pct": self.config.max_slippage_pct,
            },
            "last_updated": self.state.last_updated,
        }
