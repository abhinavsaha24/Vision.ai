"""Regime-aware meta-alpha engine with calibrated confidence."""

from __future__ import annotations

import math
from collections import deque
from typing import Any


class MetaAlphaEngine:
    def __init__(
        self,
        trend_entry_threshold: float = 0.16,
        range_entry_threshold: float = 0.13,
        min_confidence: float = 0.50,
    ):
        self.category_weights = {
            "flow": 0.50,
            "structure": 0.30,
            "volatility": 0.20,
        }
        self.signal_groups = {
            "flow": ("oi_price_divergence", "funding_extremes", "liquidation_events"),
            "structure": ("price_structure", "positioning_breakout"),
            "volatility": ("volatility_transition",),
        }
        self._history = deque(maxlen=500)
        self.trend_entry_threshold = trend_entry_threshold
        self.range_entry_threshold = range_entry_threshold
        self.min_confidence = min_confidence

    @staticmethod
    def _clip(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, v))

    def _group_score(self, signal_scores: dict[str, float], keys: tuple[str, ...]) -> float:
        vals = [self._clip(float(signal_scores.get(k, 0.0))) for k in keys]
        if not vals:
            return 0.0
        return float(sum(vals) / len(vals))

    @staticmethod
    def _edge_quality(edge_stats: dict[str, Any]) -> float:
        if not edge_stats:
            return 0.0
        vals = []
        for stat in edge_stats.values():
            if not isinstance(stat, dict):
                continue
            expectancy = float(stat.get("expectancy", 0.0) or 0.0)
            t_stat = float(stat.get("t_stat", 0.0) or 0.0)
            pf = float(stat.get("profit_factor", 1.0) or 1.0)
            trade_count = float(stat.get("trades", 0.0) or 0.0)
            quality = (
                max(0.0, min(1.0, expectancy * 400.0))
                + max(0.0, min(1.0, t_stat / 3.0))
                + max(0.0, min(1.0, (pf - 1.0) / 1.5))
                + max(0.0, min(1.0, trade_count / 120.0))
            ) / 4.0
            vals.append(quality)
        if not vals:
            return 0.0
        return float(sum(vals) / len(vals))

    def combine(
        self,
        signal_scores: dict[str, float],
        regime: str,
        edge_stats: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        flow_score = self._group_score(signal_scores, self.signal_groups["flow"])
        structure_score = self._group_score(signal_scores, self.signal_groups["structure"])
        volatility_score = self._group_score(signal_scores, self.signal_groups["volatility"])

        # Regime nudges category emphasis while preserving the 50/30/20 baseline.
        cat_w = dict(self.category_weights)
        if regime == "trend":
            cat_w["structure"] *= 1.08
            cat_w["flow"] *= 1.02
            cat_w["volatility"] *= 0.90
        else:
            cat_w["flow"] *= 1.06
            cat_w["volatility"] *= 1.04
            cat_w["structure"] *= 0.90
        ws = sum(cat_w.values()) or 1.0
        cat_w = {k: v / ws for k, v in cat_w.items()}

        score = self._clip(
            (flow_score * cat_w["flow"])
            + (structure_score * cat_w["structure"])
            + (volatility_score * cat_w["volatility"])
        )

        weighted = {
            "flow": flow_score * cat_w["flow"],
            "structure": structure_score * cat_w["structure"],
            "volatility": volatility_score * cat_w["volatility"],
        }
        agreement = 0.0
        active = [v for v in signal_scores.values() if abs(v) > 0.05]
        if active:
            sign = 1 if sum(active) >= 0 else -1
            agreement = sum(1 for x in active if (1 if x >= 0 else -1) == sign) / len(active)

        flow_sign = 1 if flow_score > 0 else (-1 if flow_score < 0 else 0)
        struct_sign = 1 if structure_score > 0 else (-1 if structure_score < 0 else 0)
        flow_alignment = "neutral"
        if abs(flow_score) < 0.10:
            flow_alignment = "neutral"
        elif flow_sign == struct_sign:
            flow_alignment = "aligned"
        else:
            flow_alignment = "conflict"

        edge_q = self._edge_quality(edge_stats or {})

        base_conf = 1.0 / (1.0 + math.exp(-((abs(score) * 3.2) + (agreement * 1.0) + (edge_q * 1.2) - 1.25)))

        if self._history:
            recent = list(self._history)[-80:]
            quality_recent = sum(abs(float(x.get("score", 0.0))) for x in recent) / len(recent)
            base_conf *= min(1.15, 0.8 + quality_recent)

        confidence = float(max(0.0, min(1.0, base_conf)))

        entry_threshold = (
            self.trend_entry_threshold if regime == "trend" else self.range_entry_threshold
        )
        if confidence < self.min_confidence or abs(score) < entry_threshold:
            decision = "none"
        elif score > 0:
            decision = "long"
        else:
            decision = "short"

        self._history.append(
            {
                "score": score,
                "confidence": confidence,
                "regime": regime,
                "decision": decision,
            }
        )

        probability = (score + 1.0) / 2.0
        canonical_signal = "neutral" if decision == "none" else decision

        contributing = sorted(
            [
                {"name": k, "contribution": float(v)}
                for k, v in weighted.items()
            ],
            key=lambda x: abs(float(x["contribution"])),
            reverse=True,
        )

        return {
            "signal": canonical_signal,
            "score": round(float(score), 6),
            "confidence": round(float(confidence), 6),
            "regime": regime,
            "decision": decision,
            "weights": {k: round(v, 6) for k, v in cat_w.items()},
            "weighted_scores": {k: round(v, 6) for k, v in weighted.items()},
            "flow_score": round(float(flow_score), 6),
            "structure_score": round(float(structure_score), 6),
            "volatility_score": round(float(volatility_score), 6),
            "flow_alignment": flow_alignment,
            "contributing_signals": [
                {"name": str(x["name"]), "contribution": round(float(x["contribution"]), 6)}
                for x in contributing
            ],
            "thresholds": {
                "entry": round(float(entry_threshold), 6),
                "confidence": round(float(self.min_confidence), 6),
            },
            "market_context": {
                "expected_edge_bps": round(float(edge_q * 100.0), 6),
            },
            "alpha_score": round(float(probability), 6),
            "probability": round(float(probability), 6),
        }

    def infer(
        self,
        prediction: dict[str, Any],
        strategy_result: dict[str, Any],
        sentiment_score: float = 0.0,
        regime: dict[str, Any] | None = None,
        market_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        regime_data = regime or {}
        market_snapshot = market_snapshot or {}

        trend_hint = str(regime_data.get("trend", "")).lower()
        market_state = str(regime_data.get("market_state", "")).upper()
        regime_label = "range"
        if market_state == "TREND" or trend_hint in {"trend", "uptrend", "downtrend"}:
            regime_label = "trend"

        model_signal = ((float(prediction.get("probability", 0.5) or 0.5) - 0.5) * 2.0)
        strategy_score = float(strategy_result.get("score", 0.0) or 0.0)

        imbalance = float(market_snapshot.get("order_book_imbalance", 0.0) or 0.0)
        volume_delta = float(market_snapshot.get("volume_delta", 0.0) or 0.0)
        volatility_expansion = float(market_snapshot.get("volatility_expansion", 0.0) or 0.0)

        signal_scores = {
            "price_structure": self._clip(strategy_score * 0.8 + model_signal * 0.45),
            "positioning_breakout": self._clip((model_signal * 0.7) + (imbalance * 0.6)),
            "funding_extremes": self._clip(sentiment_score * 0.35),
            "oi_price_divergence": self._clip((imbalance * 0.7) + (volume_delta * 0.3)),
            "liquidation_events": self._clip((imbalance * 0.2) + (volume_delta * 0.3)),
            "volatility_transition": self._clip(volatility_expansion),
        }
        out = self.combine(signal_scores=signal_scores, regime=regime_label, edge_stats={})

        spread_bps = max(0.0, float(market_snapshot.get("spread_bps", 0.0) or 0.0))
        depth_usd = max(0.0, float(market_snapshot.get("book_depth_usd", 250000.0) or 0.0))
        stale = bool(market_snapshot.get("stale", False))
        vol_label = str(regime_data.get("volatility", "")).lower()

        depth_penalty = 0.0 if depth_usd <= 0.0 else max(0.0, 8.0 - math.log10(depth_usd + 1.0) * 1.5)
        stale_penalty = 6.0 if stale else 0.0
        vol_penalty = 3.0 if vol_label == "high_volatility" else 0.0
        cost_bps = spread_bps + depth_penalty + stale_penalty + vol_penalty

        gross_edge_bps = max(
            0.0,
            (abs(float(out.get("score", 0.0))) * 45.0)
            + (abs(strategy_score) * 18.0)
            + (abs(model_signal) * 14.0),
        )
        expected_edge_bps = max(0.0, gross_edge_bps - cost_bps)

        quality_scalar = max(0.0, min(1.0, expected_edge_bps / max(gross_edge_bps, 1e-6)))
        adjusted_conf = float(out["confidence"]) * (0.55 + 0.45 * quality_scalar)
        entry = float(out["thresholds"]["entry"]) + (0.02 if vol_label == "high_volatility" else 0.0)
        entry += min(0.05, spread_bps / 500.0)

        score = float(out["score"])
        confidence_gate = self.min_confidence * 0.60
        if adjusted_conf < confidence_gate or abs(score) < entry or expected_edge_bps <= 0.0:
            decision = "none"
            signal = "neutral"
        elif score > 0:
            decision = "long"
            signal = "long"
        else:
            decision = "short"
            signal = "short"

        out["confidence"] = round(max(0.0, min(1.0, adjusted_conf)), 6)
        out["thresholds"]["entry"] = round(max(0.0, entry), 6)
        out["decision"] = decision
        out["signal"] = signal
        out["market_context"]["expected_edge_bps"] = round(expected_edge_bps, 6)
        return out
