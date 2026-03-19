"""
Strategy engine v2: Model-driven signal pipeline.

Replaces the old 11-strategy voting system with a single model-driven
decision pathway:

1. AlphaModel outputs calibrated probability
2. Confidence filter gates the signal
3. Risk manager sizes the position
4. Execution engine fills the order

Legacy strategy classes are kept for dashboard display but NO LONGER
drive trading decisions.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class StrategyEngine:
    """
    Model-driven strategy engine.

    The primary signal source is the AlphaModel's calibrated probability.
    All secondary strategies (momentum, mean-reversion, etc.) are
    informational only - they are displayed on the dashboard but
    do NOT influence trade decisions.

    This prevents the "noise averaging" problem where contradictory
    strategies cancel each other out to produce random signals.
    """

    def __init__(
        self,
        long_threshold: float = 0.65,
        short_threshold: float = 0.35,
        min_confidence: float = 0.60,
    ):
        """
        Args:
            long_threshold: probability above which to go long
            short_threshold: probability below which to go short
            min_confidence: minimum |P - 0.5| to trade (additional filter)
        """
        self.long_threshold = long_threshold
        self.short_threshold = short_threshold
        self.min_confidence = min_confidence

        # Track signal history for monitoring
        self._signal_history: deque = deque(maxlen=500)
        self._trade_count: int = 0
        self._win_count: int = 0

    def detect_regime(self, df: pd.DataFrame) -> str:
        """Detect the market regime from a local window DF."""
        if df.empty or "close" not in df or "ATR" not in df:
            return "ranging"
            
        current_close = float(df["close"].iloc[-1])
        ma_20 = float(df["close"].rolling(20).mean().iloc[-1]) if len(df) >= 20 else current_close
        atr = float(df["ATR"].iloc[-1])
        
        # Volatility check (if ATR > 2% of price)
        if atr > (current_close * 0.02):
            return "volatile"
            
        # Trend check
        dist_from_ma = abs(current_close - ma_20) / current_close
        if dist_from_ma > 0.005:  # 0.5% away from MA20
            return "trending"
            
        return "ranging"

    def get_dynamic_weight(self, strategy_name: str, regime: str, portfolio_manager) -> float:
        """Calculate dynamic weight for a strategy using recent portfolio performance."""
        if not portfolio_manager:
            return 1.0
            
        perf = portfolio_manager.get_strategy_performance(strategy_name, regime)
        return perf.get("score", 1.0)

    def generate_ensemble_signal(
        self,
        signals: Dict[str, Dict], # {"AlphaModel": {"proba": 0.65}, "Momentum": {"signal": 1}}
        regime: str,
        volatility: float,
        portfolio_manager = None
    ) -> Dict:
        """
        Produce a final execution signal by blending adaptive strategy weights.
        """
        total_weight = 0.0
        weighted_signal = 0.0
        
        best_strategy = "AlphaModel"
        max_weight = 0.0
        
        for strat_name, data in signals.items():
            # Get adaptive weight
            weight = self.get_dynamic_weight(strat_name, regime, portfolio_manager)
            
            # Phase 6: Cull bottom 30% performers (Score < 0.70)
            if weight < 0.70:
                weight = 0.0
                
            # Regime-based overrides
            if regime == "trending" and strat_name == "MeanReversion":
                weight *= 0.1 # Heavily discount mean reversion in trends
            elif regime == "ranging" and strat_name == "Momentum":
                weight *= 0.1 # Heavily discount momentum in ranges
            elif regime == "volatile":
                weight *= 0.5 # Reduce all weights in chaos
                
            sig = 0
            if "proba" in data:
                proba = data["proba"]
                if proba >= self.long_threshold: sig = 1
                elif proba <= self.short_threshold: sig = -1
            else:
                sig = data.get("signal", 0)
                
            weighted_signal += (sig * weight)
            total_weight += weight
            
            if weight > max_weight and sig != 0:
                max_weight = weight
                best_strategy = strat_name
                
        # Final blended logic
        blend = weighted_signal / total_weight if total_weight > 0 else 0
        
        final_signal = 0
        if blend > 0.3: final_signal = 1
        elif blend < -0.3: final_signal = -1
        
        # Phase 6: Noise block - unconditionally block trades in ranging regimes
        if regime == "ranging":
            final_signal = 0
            
        # Confidence calculation
        confidence = abs(blend)
        
        if volatility > 0:
            vol_normalised = min(volatility * 100, 5.0)
            vol_penalty = max(0.5, 1.0 - vol_normalised * 0.1)
            confidence *= vol_penalty
            
        if confidence < self.min_confidence:
            final_signal = 0
            
        # Record history
        self._signal_history.append({
            "confidence": round(confidence, 4),
            "signal": final_signal,
            "regime": regime,
            "dominant_strategy": best_strategy
        })
        
        return {
            "signal": final_signal,
            "confidence": confidence,
            "regime": regime,
            "dominant_strategy": best_strategy
        }

    def generate_detailed_signal(
        self,
        probability: float,
        regime: Optional[Dict] = None,
        volatility: float = 0.0,
    ) -> Dict:
        """
        Return detailed signal with full metadata for dashboard display.
        """
        regime_str = regime.get("label", "ranging") if regime else "ranging"
        
        # Backward compatibility for API dashboard
        ensemble_res = self.generate_ensemble_signal(
            signals={"AlphaModel": {"proba": probability}},
            regime=regime_str,
            volatility=volatility
        )
        
        signal = ensemble_res["signal"]
        confidence = ensemble_res["confidence"]

        direction = "LONG" if signal > 0 else "SHORT" if signal < 0 else "FLAT"

        return {
            "direction": direction,
            "signal": signal,
            "probability": round(probability, 4),
            "confidence": round(confidence, 4),
            "regime": regime_str,
            "volatility": round(volatility, 6),
            "thresholds": {
                "long": self.long_threshold,
                "short": self.short_threshold,
                "min_confidence": self.min_confidence,
            },
            "stats": self.get_signal_stats(),
        }

    def record_outcome(self, pnl: float):
        """Record a trade outcome for win-rate tracking."""
        self._trade_count += 1
        if pnl > 0:
            self._win_count += 1

    def get_signal_stats(self) -> Dict:
        """Get signal generation statistics for monitoring."""
        if not self._signal_history:
            return {"total_signals": 0}

        signals = [s["signal"] for s in self._signal_history]
        return {
            "total_signals": len(signals),
            "long_pct": round(signals.count(1) / len(signals), 3),
            "short_pct": round(signals.count(-1) / len(signals), 3),
            "flat_pct": round(signals.count(0) / len(signals), 3),
            "win_rate": (
                round(self._win_count / self._trade_count, 4)
                if self._trade_count > 0 else 0.0
            ),
            "total_trades": self._trade_count,
        }

    # ------------------------------------------------------------------
    # Compatibility layer for existing API endpoints
    # ------------------------------------------------------------------

    def get_allocation_state(self) -> Dict:
        """Legacy compatibility: return signal stats."""
        return self.get_signal_stats()
