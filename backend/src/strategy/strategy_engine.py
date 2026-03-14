"""
Strategy engine: registers and orchestrates all trading strategies.
Combines signals using regime-conditional weighting.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Safe strategy imports — missing strategies log a warning, not crash
# ------------------------------------------------------------------

try:
    from backend.src.strategy.ai_strategy import AIStrategy
except ImportError:
    AIStrategy = None
    logger.warning("AIStrategy not available")

try:
    from backend.src.strategy.momentum import MomentumStrategy
except ImportError:
    MomentumStrategy = None
    logger.warning("MomentumStrategy not available")

try:
    from backend.src.strategy.mean_reversion import MeanReversionStrategy
except ImportError:
    MeanReversionStrategy = None
    logger.warning("MeanReversionStrategy not available")

try:
    from backend.src.strategy.trend_following import BreakoutStrategy, MACrossoverStrategy
except ImportError:
    BreakoutStrategy = None
    MACrossoverStrategy = None
    logger.warning("TrendFollowing strategies not available")

try:
    from backend.src.strategy.volatility import VolatilityBreakoutStrategy, VolatilityCompressionStrategy
except ImportError:
    VolatilityBreakoutStrategy = None
    VolatilityCompressionStrategy = None
    logger.warning("Volatility strategies not available")

try:
    from backend.src.strategy.order_flow import VolumeSpikeStrategy, OrderBookImbalanceStrategy
except ImportError:
    VolumeSpikeStrategy = None
    OrderBookImbalanceStrategy = None
    logger.warning("OrderFlow strategies not available")

try:
    from backend.src.strategy.sentiment_strategy import SentimentStrategy
except ImportError:
    SentimentStrategy = None
    logger.warning("SentimentStrategy not available")

try:
    from backend.src.strategy.risk_parity_strategy import RiskParityStrategy
except ImportError:
    RiskParityStrategy = None
    logger.warning("RiskParityStrategy not available")



# ------------------------------------------------------------------
# Regime-specific weight profiles
# ------------------------------------------------------------------

REGIME_WEIGHTS = {
    "uptrend": {
        "ai": 0.25, "momentum": 0.20, "mean_reversion": 0.05,
        "breakout": 0.12, "ma_crossover": 0.08,
        "vol_breakout": 0.05, "vol_compression": 0.00,
        "volume_spike": 0.05, "ob_imbalance": 0.05,
        "sentiment": 0.10, "risk_parity": 0.05,
    },
    "downtrend": {
        "ai": 0.25, "momentum": 0.18, "mean_reversion": 0.08,
        "breakout": 0.08, "ma_crossover": 0.08,
        "vol_breakout": 0.08, "vol_compression": 0.00,
        "volume_spike": 0.05, "ob_imbalance": 0.05,
        "sentiment": 0.08, "risk_parity": 0.07,
    },
    "sideways": {
        "ai": 0.20, "momentum": 0.05, "mean_reversion": 0.20,
        "breakout": 0.05, "ma_crossover": 0.05,
        "vol_breakout": 0.05, "vol_compression": 0.12,
        "volume_spike": 0.05, "ob_imbalance": 0.08,
        "sentiment": 0.08, "risk_parity": 0.07,
    },
    "default": {
        "ai": 0.25, "momentum": 0.12, "mean_reversion": 0.12,
        "breakout": 0.08, "ma_crossover": 0.05,
        "vol_breakout": 0.05, "vol_compression": 0.05,
        "volume_spike": 0.05, "ob_imbalance": 0.08,
        "sentiment": 0.08, "risk_parity": 0.07,
    },
}


class StrategyEngine:
    """
    Multi-strategy engine with regime-aware signal generation.

    Uses a registry pattern — each strategy is loaded safely.
    Missing strategies return neutral (0) signal and log a warning.
    """

    def __init__(self):
        """Initialize all strategies with safe loading."""
        # Registry: name → instance (None if unavailable)
        self.strategies: Dict[str, object] = {}

        # Core
        self.ai = self._register("ai", AIStrategy)
        self.momentum = self._register("momentum", MomentumStrategy)
        self.mean_reversion = self._register("mean_reversion", MeanReversionStrategy)

        # Trend following
        self.breakout = self._register("breakout", BreakoutStrategy, period=20)
        self.ma_crossover = self._register("ma_crossover", MACrossoverStrategy, fast_col="SMA_7", slow_col="SMA_21")

        # Volatility
        self.vol_breakout = self._register("vol_breakout", VolatilityBreakoutStrategy, atr_multiplier=1.5)
        self.vol_compression = self._register("vol_compression", VolatilityCompressionStrategy)

        # Order flow
        self.volume_spike = self._register("volume_spike", VolumeSpikeStrategy, volume_threshold=2.0)
        self.ob_imbalance = self._register("ob_imbalance", OrderBookImbalanceStrategy, imbalance_threshold=0.7)

        # Sentiment
        self.sentiment = self._register("sentiment", SentimentStrategy)

        # Risk parity
        self.risk_parity = self._register("risk_parity", RiskParityStrategy)

        # AI confidence threshold
        self.ai_threshold = 0.55

        loaded = [k for k, v in self.strategies.items() if v is not None]
        logger.info(f"StrategyEngine loaded {len(loaded)}/{len(self.strategies)} strategies: {loaded}")

    def _register(self, name: str, cls, **kwargs):
        """Safely instantiate and register a strategy."""
        if cls is None:
            logger.warning(f"Strategy '{name}' class not available — will return neutral signal")
            self.strategies[name] = None
            return None
        try:
            instance = cls(**kwargs)
            self.strategies[name] = instance
            return instance
        except Exception as e:
            logger.error(f"Failed to initialize strategy '{name}': {e}")
            self.strategies[name] = None
            return None

    def _get_default_weight(self, name: str) -> float:
        """Return the default regime weight for a strategy."""
        return REGIME_WEIGHTS.get("default", {}).get(name, 0.0)

    def _safe_signal(self, strategy, *args, **kwargs) -> int:
        """Get signal from a strategy, returning 0 if strategy is None."""
        if strategy is None:
            return 0
        try:
            return strategy.generate_signal(*args, **kwargs)
        except Exception as e:
            logger.error(f"Strategy signal error: {e}")
            return 0

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
        ai_signal = self._safe_signal(self.ai, prediction)
        if prediction.get("probability", 0.5) >= self.ai_threshold:
            signals["ai"] = ai_signal
        else:
            signals["ai"] = 0

        # Momentum
        signals["momentum"] = self._safe_signal(self.momentum, df)

        # Mean Reversion
        signals["mean_reversion"] = self._safe_signal(self.mean_reversion, df)

        # Trend Following
        signals["breakout"] = self._safe_signal(self.breakout, df)
        signals["ma_crossover"] = self._safe_signal(self.ma_crossover, df)

        # Volatility
        signals["vol_breakout"] = self._safe_signal(self.vol_breakout, df)
        signals["vol_compression"] = self._safe_signal(self.vol_compression, df)

        # Order Flow
        signals["volume_spike"] = self._safe_signal(self.volume_spike, df)
        signals["ob_imbalance"] = self._safe_signal(self.ob_imbalance, df)

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
            "ai": self._safe_signal(self.ai, prediction) if prediction.get("probability", 0.5) >= self.ai_threshold else 0,
            "momentum": self._safe_signal(self.momentum, df),
            "mean_reversion": self._safe_signal(self.mean_reversion, df),
            "breakout": self._safe_signal(self.breakout, df),
            "ma_crossover": self._safe_signal(self.ma_crossover, df),
            "vol_breakout": self._safe_signal(self.vol_breakout, df),
            "vol_compression": self._safe_signal(self.vol_compression, df),
            "volume_spike": self._safe_signal(self.volume_spike, df),
            "ob_imbalance": self._safe_signal(self.ob_imbalance, df),
            "sentiment": self._safe_signal(self.sentiment),
            "risk_parity": self._safe_signal(self.risk_parity, df),
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