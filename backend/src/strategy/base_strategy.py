"""
Base strategy interface for all trading strategies.

All strategies must subclass BaseStrategy and implement generate_signal().
This ensures consistent interfaces, parameter management, and performance tracking.

Usage:
    class MyStrategy(BaseStrategy):
        def __init__(self):
            super().__init__(name="my_strategy", description="Custom strategy")

        def generate_signal(self, df, **kwargs) -> int:
            # Return 1 (long), -1 (short), or 0 (flat)
            ...
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List

logger = logging.getLogger("vision-ai.strategy")


@dataclass
class StrategyConfig:
    """Configuration for a strategy's tunable parameters."""

    name: str
    value: Any
    description: str = ""
    min_value: Any = None
    max_value: Any = None
    param_type: str = "float"  # "float", "int", "bool", "str"


@dataclass
class StrategyResult:
    """Result of a strategy signal generation."""

    signal: int  # 1 = long, -1 = short, 0 = flat
    confidence: float = 0.5  # 0.0 to 1.0
    reasoning: str = ""  # why this signal
    metadata: Dict = field(default_factory=dict)


@dataclass
class StrategyPerformance:
    """Performance tracking for a strategy."""

    total_signals: int = 0
    long_signals: int = 0
    short_signals: int = 0
    flat_signals: int = 0
    correct_signals: int = 0  # signals that led to profitable trades
    avg_confidence: float = 0.0

    @property
    def accuracy(self) -> float:
        if self.total_signals == 0:
            return 0.0
        return self.correct_signals / self.total_signals

    def record_signal(self, signal: int, confidence: float = 0.5):
        self.total_signals += 1
        if signal == 1:
            self.long_signals += 1
        elif signal == -1:
            self.short_signals += 1
        else:
            self.flat_signals += 1
        # Running average of confidence
        self.avg_confidence = (
            self.avg_confidence * (self.total_signals - 1) + confidence
        ) / self.total_signals

    def to_dict(self) -> Dict:
        return {
            "total_signals": self.total_signals,
            "long_signals": self.long_signals,
            "short_signals": self.short_signals,
            "flat_signals": self.flat_signals,
            "correct_signals": self.correct_signals,
            "accuracy": round(self.accuracy, 4),
            "avg_confidence": round(self.avg_confidence, 4),
        }


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.

    Subclasses must implement:
      - generate_signal(df, **kwargs) -> int

    Optional overrides:
      - get_parameters() -> List[StrategyConfig]
      - update_parameters(params: Dict)
    """

    def __init__(self, name: str = "", description: str = ""):
        self.name = name or self.__class__.__name__
        self.description = description
        self.enabled = True
        self.performance = StrategyPerformance()
        self._parameters: Dict[str, StrategyConfig] = {}

    @abstractmethod
    def generate_signal(self, *args, **kwargs) -> int:
        """
        Generate a trading signal.

        Returns:
            1 = long, -1 = short, 0 = flat/neutral
        """
        ...

    def generate_signal_with_tracking(self, *args, **kwargs) -> int:
        """Generate signal and track performance."""
        if not self.enabled:
            return 0
        signal = self.generate_signal(*args, **kwargs)
        self.performance.record_signal(signal)
        return signal

    # ---- Parameter management ----

    def get_parameters(self) -> List[StrategyConfig]:
        """Return all tunable parameters."""
        return list(self._parameters.values())

    def update_parameters(self, params: Dict[str, Any]):
        """Update strategy parameters."""
        for name, value in params.items():
            if name in self._parameters:
                self._parameters[name].value = value
                if hasattr(self, name):
                    setattr(self, name, value)
                logger.info("Strategy '%s' param '%s' -> %s", self.name, name, value)

    def register_parameter(
        self,
        name: str,
        value: Any,
        description: str = "",
        min_value: Any = None,
        max_value: Any = None,
    ):
        """Register a tunable parameter."""
        self._parameters[name] = StrategyConfig(
            name=name,
            value=value,
            description=description,
            min_value=min_value,
            max_value=max_value,
        )

    # ---- Info ----

    def get_info(self) -> Dict:
        """Get strategy information."""
        return {
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "parameters": {p.name: p.value for p in self._parameters.values()},
            "performance": self.performance.to_dict(),
        }

    def __repr__(self):
        return f"<{self.__class__.__name__}(name={self.name}, enabled={self.enabled})>"
