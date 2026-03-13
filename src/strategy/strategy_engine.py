"""
Strategy engine: registers and orchestrates all trading strategies.
Combines signals using regime-conditional weighting.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import pandas as pd

from src.strategy.ai_strategy import AIStrategy
from src.strategy.momentum_strategy import MomentumStrategy
from src.strategy.mean_reversion import MeanReversionStrategy
from src.strategy.trend_following import BreakoutStrategy, MACrossoverStrategy
from src.strategy.volatility_strategy import VolatilityBreakoutStrategy, VolatilityCompressionStrategy
from src.strategy.order_flow_strategy import VolumeSpikeStrategy, OrderBookImbalanceStrategy

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Regime-specific weight profiles
# ------------------------------------------------------------------

REGIME_WEIGHTS = {
    "uptrend": {
        "ai": 0.30, "momentum": 0.25, "mean_reversion": 0.05,
        "breakout": 0.15, "ma_crossover": 0.10,
        "vol_breakout": 0.05, "vol_compression": 0.00,
        "volume_spike": 0.05, "ob_imbalance": 0.05,
    },
    "downtrend": {
        "ai": 0.30, "momentum": 0.20, "mean_reversion": 0.10,
        "breakout": 0.10, "ma_crossover": 0.10,
        "vol_breakout": 0.10, "vol_compression": 0.00,
        "volume_spike": 0.05, "ob_imbalance": 0.05,
    },
    "sideways": {
        "ai": 0.25, "momentum": 0.05, "mean_reversion": 0.25,
        "breakout": 0.05, "ma_crossover": 0.05,
        "vol_breakout": 0.05, "vol_compression": 0.15,
        "volume_spike": 0.05, "ob_imbalance": 0.10,
    },
    "default": {
        "ai": 0.30, "momentum": 0.15, "mean_reversion": 0.15,
        "breakout": 0.10, "ma_crossover": 0.05,
        "vol_breakout": 0.05, "vol_compression": 0.05,
        "volume_spike": 0.05, "ob_imbalance": 0.10,
    },
}


class StrategyEngine:
    """
    Multi-strategy engine with regime-aware signal generation.
    """

    def __init__(self):
        # Core strategies
        self.ai = AIStrategy()
        self.momentum = MomentumStrategy()
        self.mean_reversion = MeanReversionStrategy()

        # Trend following
        self.breakout = BreakoutStrategy(period=20)
        self.ma_crossover = MACrossoverStrategy(fast_col="SMA_7", slow_col="SMA_21")

        # Volatility
        self.vol_breakout = VolatilityBreakoutStrategy(atr_multiplier=1.5)
        self.vol_compression = VolatilityCompressionStrategy()

        # Order flow
        self.volume_spike = VolumeSpikeStrategy(volume_threshold=2.0)
        self.ob_imbalance = OrderBookImbalanceStrategy(imbalance_threshold=0.7)

        # AI confidence threshold
        self.ai_threshold = 0.55

    def generate_signal(self, df: pd.DataFrame, prediction: Dict,
                        regime: Optional[Dict] = None) -> int:
        """
        Generate combined signal from all strategies.

        Args:
            df: market data with features
            prediction: AI prediction dict with 'probability'
            regime: optional regime dict with 'trend' key

        Returns:
            1 (long), -1 (short), or 0 (flat)
        """
        # Select weights based on regime
        trend = "default"
        if regime and isinstance(regime, dict):
            trend = regime.get("trend", "default")
        weights = REGIME_WEIGHTS.get(trend, REGIME_WEIGHTS["default"])

        signals = {}

        # AI Strategy
        ai_signal = self.ai.generate_signal(prediction)
        if prediction.get("probability", 0.5) >= self.ai_threshold:
            signals["ai"] = ai_signal
        else:
            signals["ai"] = 0

        # Momentum
        signals["momentum"] = self.momentum.generate_signal(df)

        # Mean Reversion
        signals["mean_reversion"] = self.mean_reversion.generate_signal(df)

        # Trend Following
        signals["breakout"] = self.breakout.generate_signal(df)
        signals["ma_crossover"] = self.ma_crossover.generate_signal(df)

        # Volatility
        signals["vol_breakout"] = self.vol_breakout.generate_signal(df)
        signals["vol_compression"] = self.vol_compression.generate_signal(df)

        # Order Flow
        signals["volume_spike"] = self.volume_spike.generate_signal(df)
        signals["ob_imbalance"] = self.ob_imbalance.generate_signal(df)

        # Weighted aggregation
        score = 0.0
        for name, signal in signals.items():
            weight = weights.get(name, 0)
            score += signal * weight

        # Final decision
        if score > 0.1:
            return 1
        if score < -0.1:
            return -1
        return 0

    def generate_detailed_signal(self, df: pd.DataFrame, prediction: Dict,
                                 regime: Optional[Dict] = None) -> Dict:
        """Return detailed signal breakdown."""
        trend = "default"
        if regime and isinstance(regime, dict):
            trend = regime.get("trend", "default")
        weights = REGIME_WEIGHTS.get(trend, REGIME_WEIGHTS["default"])

        signals = {
            "ai": self.ai.generate_signal(prediction) if prediction.get("probability", 0.5) >= self.ai_threshold else 0,
            "momentum": self.momentum.generate_signal(df),
            "mean_reversion": self.mean_reversion.generate_signal(df),
            "breakout": self.breakout.generate_signal(df),
            "ma_crossover": self.ma_crossover.generate_signal(df),
            "vol_breakout": self.vol_breakout.generate_signal(df),
            "vol_compression": self.vol_compression.generate_signal(df),
            "volume_spike": self.volume_spike.generate_signal(df),
            "ob_imbalance": self.ob_imbalance.generate_signal(df),
        }

        score = sum(signals[k] * weights.get(k, 0) for k in signals)

        direction = "LONG" if score > 0.1 else "SHORT" if score < -0.1 else "FLAT"

        return {
            "direction": direction,
            "score": round(score, 4),
            "regime": trend,
            "signals": signals,
            "weights": weights,
        }