"""Institutional meta-alpha engine for weighted multi-signal aggregation."""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Dict, Optional


class MetaAlphaEngine:
    """Combines model, microstructure, volatility, and optional sentiment into alpha."""

    def __init__(self):
        self.base_weights = {
            "model_probability": 0.35,
            "strategy_alignment": 0.12,
            "order_book_imbalance": 0.22,
            "volume_delta": 0.15,
            "volatility_expansion": 0.18,
            "liquidity_quality": 0.10,
            "sentiment": 0.10,
            "spread_penalty": 0.10,
        }
        self._history = deque(maxlen=500)
        self._contribution_totals = {name: 0.0 for name in self.base_weights}

    @staticmethod
    def _clip(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, value))

    def _robust_scale(self, value: float, scale: float) -> float:
        # tanh bounds outliers while keeping ordering information.
        if scale <= 0:
            return 0.0
        return self._clip(math.tanh(value / scale))

    def _expected_edge_after_costs_bps(
        self,
        model_signal: float,
        strategy_component: float,
        imbalance_component: float,
        volume_delta_component: float,
        vol_expansion_component: float,
        spread_bps: float,
        stale: bool,
    ) -> float:
        # Conservative expected edge model to avoid overtrading under friction.
        gross_edge_bps = (
            abs(model_signal) * 26.0
            + abs(strategy_component) * 16.0
            + abs(imbalance_component) * 18.0
            + abs(volume_delta_component) * 14.0
            + max(0.0, vol_expansion_component) * 10.0
        )
        execution_cost_bps = spread_bps + (spread_bps * 0.6) + 2.5
        stale_penalty = 5.0 if stale else 0.0
        return gross_edge_bps - execution_cost_bps - stale_penalty

    @staticmethod
    def _consensus_score(*components: float) -> float:
        active = [c for c in components if abs(c) >= 0.05]
        if not active:
            return 0.0
        direction = 1 if sum(active) >= 0 else -1
        aligned = sum(1 for c in active if (1 if c >= 0 else -1) == direction)
        return aligned / float(len(active))

    def _dynamic_thresholds(
        self,
        regime: Dict[str, Any],
        market_snapshot: Dict[str, Any],
        expected_edge_bps: float,
        consensus_score: float,
    ) -> Dict[str, float]:
        buy = 0.60
        sell = 0.40

        if regime.get("market_state") == "VOLATILE" or regime.get("volatility") == "high_volatility":
            buy += 0.03
            sell -= 0.03

        spread_bps = float(market_snapshot.get("spread_bps", 0.0) or 0.0)
        if spread_bps >= 15:
            buy += 0.02
            sell -= 0.02
        if market_snapshot.get("stale"):
            buy += 0.05
            sell -= 0.05

        # Tighten entries when current expected net edge is weak.
        if expected_edge_bps < 3.0:
            buy += 0.03
            sell -= 0.03
        elif expected_edge_bps >= 12.0 and consensus_score >= 0.75:
            buy -= 0.015
            sell += 0.015

        # Recent low-quality alpha stream should adaptively reduce aggressiveness.
        recent = list(self._history)[-40:]
        if recent:
            avg_recent_edge = sum(float(h.get("expected_edge_bps", 0.0)) for h in recent) / len(recent)
            if avg_recent_edge < 2.0:
                buy += 0.015
                sell -= 0.015

        buy = min(0.72, max(0.56, buy))
        sell = max(0.28, min(0.44, sell))
        return {"buy": buy, "sell": sell}

    def infer(
        self,
        prediction: Dict[str, Any],
        strategy_result: Dict[str, Any],
        sentiment_score: float = 0.0,
        regime: Optional[Dict[str, Any]] = None,
        market_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        regime = regime or {}
        market_snapshot = market_snapshot or {}
        weights = self._weights_for_regime(regime)

        model_probability = float(prediction.get("probability", 0.5) or 0.5)
        model_signal = self._clip((model_probability - 0.5) * 2.0, -1.0, 1.0)
        strategy_component = self._robust_scale(
            float(strategy_result.get("score", 0.0) or 0.0), 0.5
        )

        sentiment_component = self._robust_scale(float(sentiment_score or 0.0), 0.6)
        imbalance_component = self._robust_scale(
            float(market_snapshot.get("order_book_imbalance", 0.0) or 0.0), 0.65
        )
        volume_delta_component = self._robust_scale(
            float(market_snapshot.get("volume_delta", 0.0) or 0.0), 0.8
        )
        vol_expansion_component = self._robust_scale(
            float(market_snapshot.get("volatility_expansion", 0.0) or 0.0), 0.8
        )
        spread_bps = float(market_snapshot.get("spread_bps", 0.0) or 0.0)
        book_depth_usd = float(market_snapshot.get("book_depth_usd", 0.0) or 0.0)
        depth_score = self._clip(book_depth_usd / 500000.0, 0.0, 1.0)
        spread_quality = self._clip(1.0 - (spread_bps / 25.0), 0.0, 1.0)
        liquidity_quality = self._clip((depth_score * 0.6) + (spread_quality * 0.4), 0.0, 1.0)
        liquidity_component = self._clip((liquidity_quality * 2.0) - 1.0, -1.0, 1.0)
        spread_penalty = -self._clip(spread_bps / 25.0, 0.0, 1.0)

        stale = bool(market_snapshot.get("stale", False))
        expected_edge_bps = self._expected_edge_after_costs_bps(
            model_signal=model_signal,
            strategy_component=strategy_component,
            imbalance_component=imbalance_component,
            volume_delta_component=volume_delta_component,
            vol_expansion_component=vol_expansion_component,
            spread_bps=spread_bps,
            stale=stale,
        )

        components = {
            "model_probability": round(model_signal, 6),
            "strategy_alignment": round(strategy_component, 6),
            "order_book_imbalance": round(imbalance_component, 6),
            "volume_delta": round(volume_delta_component, 6),
            "volatility_expansion": round(vol_expansion_component, 6),
            "liquidity_quality": round(liquidity_component, 6),
            "sentiment": round(sentiment_component, 6),
            "spread_penalty": round(spread_penalty, 6),
        }

        weighted_components = {
            name: round(value * weights.get(name, 0.0), 6)
            for name, value in components.items()
        }
        # Convert weighted signed score into bounded 0..1 alpha score.
        alpha_raw = sum(weighted_components.values())
        alpha_score = round((self._clip(alpha_raw, -1.0, 1.0) + 1.0) / 2.0, 6)
        logistic_input = self._clip((alpha_score - 0.5) * 6.0, -8.0, 8.0)
        probability = round(1.0 / (1.0 + math.exp(-logistic_input)), 6)

        directional_consensus = self._consensus_score(
            model_signal,
            strategy_component,
            imbalance_component,
            volume_delta_component,
        )
        agreement_score = self._clip(
            abs(sum(1 if v > 0 else -1 for v in components.values() if abs(v) > 0.05))
            / max(1.0, float(len(components))),
            0.0,
            1.0,
        )
        confidence = min(
            1.0,
            abs(alpha_score - 0.5) * 2.0
            + abs(model_signal) * 0.20
            + agreement_score * 0.20
            + directional_consensus * 0.20,
        )
        if stale:
            confidence *= 0.5
        if spread_bps >= 20:
            confidence *= 0.75

        # Net expected edge should directly scale confidence and trade selectivity.
        if expected_edge_bps < 0:
            confidence *= 0.35
        elif expected_edge_bps < 5:
            confidence *= 0.70
        elif expected_edge_bps >= 15:
            confidence = min(1.0, confidence * 1.08)

        confidence = round(self._clip(confidence, 0.0, 1.0), 6)

        thresholds = self._dynamic_thresholds(
            regime,
            market_snapshot,
            expected_edge_bps=expected_edge_bps,
            consensus_score=directional_consensus,
        )

        if probability >= thresholds["buy"]:
            signal = "BUY"
        elif probability <= thresholds["sell"]:
            signal = "SELL"
        else:
            signal = "HOLD"

        contributors = [
            {
                "name": name,
                "raw": components[name],
                "weight": round(weights.get(name, 0.0), 6),
                "contribution": weighted_components[name],
            }
            for name in sorted(
                weighted_components,
                key=lambda item: abs(weighted_components[item]),
                reverse=True,
            )
        ]

        for name, value in weighted_components.items():
            self._contribution_totals[name] = self._contribution_totals.get(
                name, 0.0
            ) + float(abs(value))
        self._history.append(
            {
                "signal": signal,
                "probability": probability,
                "confidence": confidence,
                "alpha_score": alpha_score,
                "alpha_raw": round(alpha_raw, 6),
                "spread_bps": spread_bps,
                "stale": stale,
                "expected_edge_bps": round(expected_edge_bps, 4),
            }
        )

        importance_total = sum(self._contribution_totals.values()) or 1.0
        signal_importance = {
            name: round(value / importance_total, 6)
            for name, value in sorted(
                self._contribution_totals.items(), key=lambda kv: kv[1], reverse=True
            )
        }

        return {
            "signal": signal,
            "probability": probability,
            "confidence": confidence,
            "alpha_score": alpha_score,
            "contributing_signals": contributors,
            "weights": {k: round(v, 6) for k, v in weights.items()},
            "thresholds": {
                "buy": round(thresholds["buy"], 4),
                "sell": round(thresholds["sell"], 4),
            },
            "signal_importance": signal_importance,
            "market_context": {
                "spread_bps": round(spread_bps, 4),
                "order_book_imbalance": round(imbalance_component, 6),
                "volume_delta": round(volume_delta_component, 6),
                "volatility_expansion": round(vol_expansion_component, 6),
                "liquidity_quality": round(liquidity_quality, 6),
                "directional_consensus": round(directional_consensus, 6),
                "expected_edge_bps": round(expected_edge_bps, 4),
                "stale": stale,
                "connection_state": market_snapshot.get("connection_state", "unknown"),
            },
        }

    def _weights_for_regime(self, regime: Dict[str, Any]) -> Dict[str, float]:
        weights = dict(self.base_weights)
        market_state = regime.get("market_state", "UNKNOWN")
        volatility = regime.get("volatility", "unknown")

        if market_state == "TREND":
            weights["model_probability"] *= 1.15
            weights["strategy_alignment"] *= 1.10
            weights["order_book_imbalance"] *= 1.10
        elif market_state == "RANGE":
            weights["order_book_imbalance"] *= 1.20
            weights["volume_delta"] *= 1.10
            weights["strategy_alignment"] *= 0.95

        if market_state == "VOLATILE" or volatility == "high_volatility":
            weights["spread_penalty"] *= 1.40
            weights["model_probability"] *= 0.85
            weights["volatility_expansion"] *= 1.30
            weights["liquidity_quality"] *= 1.10
            weights["strategy_alignment"] *= 0.85

        total = sum(weights.values()) or 1.0
        return {name: value / total for name, value in weights.items()}
