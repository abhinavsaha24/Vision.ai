from __future__ import annotations

from backend.src.platform.live.types import DetectedEvent, MicrostructureFeatures, SignalDecision


class LatencyAwareFilter:
    def __init__(
        self,
        max_signal_latency_ms: float,
        max_event_staleness_ms: float,
        max_spread_bps: float,
        min_visible_liquidity: float,
    ):
        self.max_signal_latency_ms = max_signal_latency_ms
        self.max_event_staleness_ms = max_event_staleness_ms
        self.max_spread_bps = max_spread_bps
        self.min_visible_liquidity = min_visible_liquidity

    def accepts(self, now_ms: int, event: DetectedEvent, features: MicrostructureFeatures) -> tuple[bool, str]:
        if features.latency_ms > self.max_signal_latency_ms:
            return False, "latency_too_high"
        if now_ms - event.ts_ms > self.max_event_staleness_ms:
            return False, "event_stale"
        if features.spread_bps > self.max_spread_bps:
            return False, "spread_too_wide"
        if features.visible_liquidity < self.min_visible_liquidity:
            return False, "insufficient_liquidity"
        if not features.impact_measurable:
            return False, "impact_not_measurable"
        if not features.liquidity_regime_clear:
            return False, "liquidity_regime_unclear"
        return True, "ok"


class SignalEngine:
    """Generates directional signals from liquidity-participant behavior."""

    def generate(self, event: DetectedEvent, features: MicrostructureFeatures) -> SignalDecision | None:
        event_type = event.event_type
        sweep_side = str(event.payload.get("sweep_side", "buy"))
        no_refill = float(features.refill_rate) <= 0.35
        has_refill = float(features.refill_rate) >= 0.75
        measurable = features.impact_measurable and features.liquidity_present

        side = ""
        reason = ""

        # Reversal alpha: sweep fails and depth rebuilds.
        if event_type == "failed_breakout" and has_refill and measurable:
            if sweep_side == "sell":
                side = "long"
                reason = "sell_sweep_failed_depth_rebuild"
            elif sweep_side == "buy":
                side = "short"
                reason = "buy_sweep_failed_depth_rebuild"

        # Continuation alpha: sweep with no refill and persistent impact.
        if not side and event_type == "liquidity_sweep" and no_refill and measurable:
            if sweep_side == "sell" and features.book_depth_imbalance < -0.05 and features.impact_persistence > 0.2:
                side = "short"
                reason = "sell_sweep_no_refill_continuation"
            elif sweep_side == "buy" and features.book_depth_imbalance > 0.05 and features.impact_persistence > 0.2:
                side = "long"
                reason = "buy_sweep_no_refill_continuation"

        # Absorption traps: one side is forced, depth holds and rebalances.
        if not side and event_type == "absorption" and measurable:
            if sweep_side == "sell" and features.book_depth_imbalance > 0.08:
                side = "long"
                reason = "sell_absorption_trapped_sellers"
            elif sweep_side == "buy" and features.book_depth_imbalance < -0.08:
                side = "short"
                reason = "buy_absorption_trapped_buyers"

        # Forced flow continuation (microstructure state transition event).
        if not side and event_type == "forced_flow_continuation" and measurable:
            if sweep_side == "buy" and features.queue_depletion_rate > features.queue_refill_rate:
                side = "long"
                reason = "forced_buy_flow_continuation"
            elif sweep_side == "sell" and features.queue_depletion_rate > features.queue_refill_rate:
                side = "short"
                reason = "forced_sell_flow_continuation"

        # Absorption reversal from state transition.
        if not side and event_type == "absorption_reversal" and measurable:
            if sweep_side == "buy" and features.reversal_probability > 0.5:
                side = "short"
                reason = "buy_pressure_absorption_reversal"
            elif sweep_side == "sell" and features.reversal_probability > 0.5:
                side = "long"
                reason = "sell_pressure_absorption_reversal"

        # Queue failure breakout.
        if not side and event_type == "queue_failure_breakout" and measurable:
            if sweep_side == "buy" and features.refill_latency_ms > 300.0:
                side = "long"
                reason = "buy_queue_failure_breakout"
            elif sweep_side == "sell" and features.refill_latency_ms > 300.0:
                side = "short"
                reason = "sell_queue_failure_breakout"

        # Inventory unwind.
        if not side and event_type == "inventory_unwind" and measurable:
            if sweep_side == "buy":
                side = "short"
                reason = "post_buy_inventory_unwind"
            elif sweep_side == "sell":
                side = "long"
                reason = "post_sell_inventory_unwind"

        # Cross-venue arbitrage trigger.
        if not side and event_type == "cross_venue_arbitrage" and measurable:
            if features.cross_venue_spread_divergence_bps > 0.0:
                side = "long"
                reason = "cross_venue_stale_quote_arb_long"
            elif features.cross_venue_spread_divergence_bps < 0.0:
                side = "short"
                reason = "cross_venue_stale_quote_arb_short"

        if not side:
            return None

        score = self._score(event, features)
        if score < 0.25:
            return None

        seq = features.sequence or {}
        return SignalDecision(
            symbol=event.symbol,
            ts_ms=event.ts_ms,
            side=side,
            reason=reason,
            score=score,
            event_type=event.event_type,
            features={
                "imbalance": float(features.imbalance),
                "impact": float(features.impact),
                "absorption": float(features.absorption),
                "book_top_imbalance": float(features.book_top_imbalance),
                "book_depth_imbalance": float(features.book_depth_imbalance),
                "liquidity_gap_bps": float(features.liquidity_gap_bps),
                "order_book_slope": float(features.order_book_slope),
                "refill_rate": float(features.refill_rate),
                "refill_velocity": float(features.refill_velocity),
                "depletion_rate": float(features.depletion_rate),
                "consumed_liquidity": float(features.consumed_liquidity),
                "depth_collapse_ratio": float(features.depth_collapse_ratio),
                "queue_depletion_rate": float(features.queue_depletion_rate),
                "queue_refill_rate": float(features.queue_refill_rate),
                "add_volume_rate": float(features.add_volume_rate),
                "cancel_volume_rate": float(features.cancel_volume_rate),
                "sweep_to_refill_ratio": float(features.sweep_to_refill_ratio),
                "refill_latency_ms": float(features.refill_latency_ms),
                "impact_persistence": float(features.impact_persistence),
                "reversal_probability": float(features.reversal_probability),
                "signed_flow_z": float(features.signed_flow_z),
                "burst_cluster_score": float(features.burst_cluster_score),
                "impact_per_volume": float(features.impact_per_volume),
                "recovery_slope": float(features.recovery_slope),
                "liquidity_resilience_score": float(features.liquidity_resilience_score),
                "cross_venue_spread_divergence_bps": float(features.cross_venue_spread_divergence_bps),
                "stale_quote_score": float(features.stale_quote_score),
                "hedge_sync_score": float(features.hedge_sync_score),
                "trade_intensity": float(features.trade_intensity),
                "aggression_velocity": float(features.aggression_velocity),
                "spread_bps": float(features.spread_bps),
                "latency_ms": float(features.latency_ms),
                "consecutive_sweeps": float(seq.get("consecutive_sweeps", 0.0)),
                "impact_decay": float(seq.get("impact_decay", 1.0)),
            },
        )

    @staticmethod
    def _score(event: DetectedEvent, features: MicrostructureFeatures) -> float:
        strength = min(1.0, max(0.0, float(event.strength)))
        impact = min(1.0, abs(features.impact) * 25.0)
        imbalance = min(1.0, abs(features.book_depth_imbalance) * 3.0)
        refill_separation = min(1.0, abs(features.refill_rate - 1.0))
        persistence = min(1.0, max(0.0, features.impact_persistence))
        reversal = min(1.0, max(0.0, features.reversal_probability))
        raw = (
            (strength * 0.25)
            + (impact * 0.20)
            + (imbalance * 0.20)
            + (refill_separation * 0.15)
            + (persistence * 0.10)
            + (reversal * 0.10)
        )
        return max(0.0, min(1.0, raw))
