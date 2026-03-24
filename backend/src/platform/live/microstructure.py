from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from backend.src.platform.live.types import (
    DepthTop,
    DetectedEvent,
    MicrostructureFeatures,
    TradeTick,
    WindowMetrics,
)


@dataclass(slots=True)
class _TradePoint:
    ts_ms: int
    price: float
    quantity: float
    signed_qty: float


class SubSecondAggregator:
    """Maintains rolling trade windows at 1s/5s/10s."""

    WINDOW_SECONDS = (1, 5, 10)

    def __init__(self):
        self._trades: deque[_TradePoint] = deque()

    def on_trade(self, trade: TradeTick) -> dict[int, WindowMetrics]:
        signed_qty = trade.quantity if trade.aggressor_side == "buy" else -trade.quantity
        self._trades.append(
            _TradePoint(
                ts_ms=trade.exchange_ts_ms,
                price=trade.price,
                quantity=trade.quantity,
                signed_qty=signed_qty,
            )
        )

        cutoff = trade.exchange_ts_ms - (10 * 1000)
        while self._trades and self._trades[0].ts_ms < cutoff:
            self._trades.popleft()

        c1 = trade.exchange_ts_ms - 1000
        c5 = trade.exchange_ts_ms - 5000
        c10 = trade.exchange_ts_ms - 10000

        # Keep hot-path deterministic and allocation-light: single reverse pass.
        acc = {
            1: {"tv": 0.0, "sv": 0.0, "bv": 0.0, "sev": 0.0, "tc": 0, "pv": 0.0, "fp": 0.0, "lp": 0.0, "set": False},
            5: {"tv": 0.0, "sv": 0.0, "bv": 0.0, "sev": 0.0, "tc": 0, "pv": 0.0, "fp": 0.0, "lp": 0.0, "set": False},
            10: {"tv": 0.0, "sv": 0.0, "bv": 0.0, "sev": 0.0, "tc": 0, "pv": 0.0, "fp": 0.0, "lp": 0.0, "set": False},
        }

        for t in reversed(self._trades):
            ts = t.ts_ms
            if ts < c10:
                break
            for sec, c in ((1, c1), (5, c5), (10, c10)):
                if ts < c:
                    continue
                a = acc[sec]
                if not a["set"]:
                    a["lp"] = t.price
                    a["fp"] = t.price
                    a["set"] = True
                else:
                    a["fp"] = t.price
                a["tv"] += t.quantity
                a["sv"] += t.signed_qty
                if t.signed_qty > 0:
                    a["bv"] += t.quantity
                elif t.signed_qty < 0:
                    a["sev"] += t.quantity
                a["tc"] += 1
                a["pv"] += t.price * t.quantity

        return {
            1: self._compute_window_metrics_from_accum(1, acc[1]),
            5: self._compute_window_metrics_from_accum(5, acc[5]),
            10: self._compute_window_metrics_from_accum(10, acc[10]),
        }

    @staticmethod
    def _compute_window_metrics_from_accum(window_seconds: int, a: dict[str, float | int | bool]) -> WindowMetrics:
        total_volume = float(a["tv"])
        if total_volume <= 0.0:
            return WindowMetrics(
                window_seconds=window_seconds,
                total_volume=0.0,
                signed_volume=0.0,
                buy_volume=0.0,
                sell_volume=0.0,
                trade_count=0,
                price_change=0.0,
                vwap=0.0,
            )

        first_price = float(a["fp"])
        last_price = float(a["lp"])
        return WindowMetrics(
            window_seconds=window_seconds,
            total_volume=total_volume,
            signed_volume=float(a["sv"]),
            buy_volume=float(a["bv"]),
            sell_volume=abs(float(a["sev"])),
            trade_count=int(a["tc"]),
            price_change=(last_price - first_price),
            vwap=(float(a["pv"]) / max(total_volume, 1e-9)),
        )

    @staticmethod
    def _compute_window_metrics(window_seconds: int, trades: list[_TradePoint]) -> WindowMetrics:
        if not trades:
            return WindowMetrics(
                window_seconds=window_seconds,
                total_volume=0.0,
                signed_volume=0.0,
                buy_volume=0.0,
                sell_volume=0.0,
                trade_count=0,
                price_change=0.0,
                vwap=0.0,
            )

        total_volume = sum(t.quantity for t in trades)
        signed_volume = sum(t.signed_qty for t in trades)
        buy_volume = sum(t.quantity for t in trades if t.signed_qty > 0)
        sell_volume = sum(t.quantity for t in trades if t.signed_qty < 0)
        pv = sum(t.price * t.quantity for t in trades)
        first_price = trades[0].price
        last_price = trades[-1].price
        return WindowMetrics(
            window_seconds=window_seconds,
            total_volume=total_volume,
            signed_volume=signed_volume,
            buy_volume=buy_volume,
            sell_volume=abs(sell_volume),
            trade_count=len(trades),
            price_change=(last_price - first_price),
            vwap=(pv / max(total_volume, 1e-9)),
        )


class MicrostructureEngine:
    def __init__(self):
        self._depth_history: deque[tuple[int, float, float, float]] = deque(maxlen=200)
        self._signed_flow_history: deque[float] = deque(maxlen=240)
        self._burst_ts: deque[int] = deque(maxlen=256)
        self._active_sweep: dict[str, float] | None = None
        self._last_sweep_consumed: float = 0.0
        self._prev_bid_levels: dict[float, float] = {}
        self._prev_ask_levels: dict[float, float] = {}

    @staticmethod
    def _level_map(levels: list[tuple[float, float]]) -> dict[float, float]:
        return {float(p): float(q) for p, q in levels}

    @staticmethod
    def _add_cancel_volume(prev: dict[float, float], cur: dict[float, float]) -> tuple[float, float]:
        add = 0.0
        cancel = 0.0
        for price in set(prev.keys()) | set(cur.keys()):
            delta = cur.get(price, 0.0) - prev.get(price, 0.0)
            if delta > 0.0:
                add += delta
            elif delta < 0.0:
                cancel += abs(delta)
        return add, cancel

    def compute(
        self,
        symbol: str,
        ts_ms: int,
        windows: dict[int, WindowMetrics],
        depth: DepthTop | None,
        latency_ms: float,
        sequence: dict[str, float],
    ) -> MicrostructureFeatures:
        missing = [k for k in (1, 5) if k not in windows]
        if missing:
            raise ValueError(f"microstructure_windows_missing keys={missing} available={sorted(windows.keys())}")
        one = windows[1]
        five = windows[5]

        total_volume = max(one.total_volume, 1e-9)
        imbalance = (one.buy_volume - one.sell_volume) / total_volume
        aggression_velocity = one.total_volume / 1.0
        trade_intensity = one.trade_count / 1.0

        impact = one.price_change / max(one.total_volume, 1e-9)
        absorption = five.total_volume / (abs(five.price_change) + 1e-6)

        spread_bps = 999.0
        visible_liquidity = 0.0
        ref_price = one.vwap if one.vwap > 0 else 0.0
        book_top_imbalance = 0.0
        book_depth_imbalance = 0.0
        liquidity_gap_bps = 0.0
        order_book_slope = 0.0
        refill_rate = 0.0
        refill_velocity = 0.0
        depletion_rate = 0.0
        imbalance_shift = 0.0
        consumed_liquidity = 0.0
        depth_collapse_ratio = 0.0
        queue_depletion_rate = 0.0
        queue_refill_rate = 0.0
        add_volume_rate = 0.0
        cancel_volume_rate = 0.0
        sweep_to_refill_ratio = 0.0
        refill_latency_ms = 0.0

        if depth is not None and depth.mid > 0:
            ref_price = depth.mid
            spread_bps = (depth.spread / depth.mid) * 10000.0
            total_bid = sum(q for _, q in depth.bids)
            total_ask = sum(q for _, q in depth.asks)
            visible_liquidity = total_bid + total_ask

            top_total = max(depth.bid_qty + depth.ask_qty, 1e-9)
            book_top_imbalance = (depth.bid_qty - depth.ask_qty) / top_total
            book_depth_imbalance = (total_bid - total_ask) / max(visible_liquidity, 1e-9)
            liquidity_gap_bps = self._liquidity_gaps_bps(depth)
            order_book_slope = self._book_slope(depth)

            prev = self._depth_history[-1] if self._depth_history else None
            self._depth_history.append((ts_ms, visible_liquidity, book_depth_imbalance, ref_price))
            if prev is not None:
                dt_s = max(1e-3, (ts_ms - prev[0]) / 1000.0)
                prev_liq = max(prev[1], 1e-9)
                imbalance_shift = book_depth_imbalance - prev[2]

                if visible_liquidity < prev_liq:
                    consumed_liquidity = prev_liq - visible_liquidity
                    depletion_rate = consumed_liquidity / dt_s
                    self._last_sweep_consumed += consumed_liquidity
                else:
                    refill_velocity = (visible_liquidity - prev_liq) / dt_s
                refill_rate = visible_liquidity / prev_liq
                depth_collapse_ratio = max(0.0, (prev_liq - visible_liquidity) / prev_liq)

                # Queue dynamics approximation from level-by-level changes.
                cur_bid_levels = self._level_map(depth.bids)
                cur_ask_levels = self._level_map(depth.asks)
                add_bid, cancel_bid = self._add_cancel_volume(self._prev_bid_levels, cur_bid_levels)
                add_ask, cancel_ask = self._add_cancel_volume(self._prev_ask_levels, cur_ask_levels)
                add_volume_rate = (add_bid + add_ask) / dt_s
                cancel_volume_rate = (cancel_bid + cancel_ask) / dt_s
                queue_refill_rate = add_volume_rate
                queue_depletion_rate = cancel_volume_rate

                if self._active_sweep is None and depth_collapse_ratio >= 0.12:
                    self._active_sweep = {
                        "start_ts": float(ts_ms),
                        "pre_liq": float(prev_liq),
                    }
                    self._last_sweep_consumed = max(self._last_sweep_consumed, consumed_liquidity)
                if self._active_sweep is not None:
                    pre_liq = max(float(self._active_sweep.get("pre_liq", visible_liquidity)), 1e-9)
                    if visible_liquidity >= 0.90 * pre_liq:
                        refill_latency_ms = max(0.0, float(ts_ms) - float(self._active_sweep.get("start_ts", ts_ms)))
                        self._active_sweep = None
                        self._last_sweep_consumed = 0.0
                    else:
                        refill_latency_ms = max(0.0, float(ts_ms) - float(self._active_sweep.get("start_ts", ts_ms)))

                if refill_velocity > 0.0:
                    sweep_to_refill_ratio = self._last_sweep_consumed / max(refill_velocity, 1e-9)

            self._prev_bid_levels = self._level_map(depth.bids)
            self._prev_ask_levels = self._level_map(depth.asks)

        impact_persistence = float(sequence.get("impact_persistence", 0.0))
        reversal_probability = float(sequence.get("reversal_probability", 0.0))

        self._signed_flow_history.append(float(one.signed_volume))
        signed_flow_z = 0.0
        if len(self._signed_flow_history) >= 20:
            vals = list(self._signed_flow_history)
            mu = sum(vals) / len(vals)
            var = sum((v - mu) ** 2 for v in vals) / max(1, len(vals) - 1)
            sd = var ** 0.5
            if sd > 1e-9:
                signed_flow_z = (float(one.signed_volume) - mu) / sd

        burst_trigger = one.total_volume >= max(0.8, 1.4 * max(1e-9, five.total_volume / 5.0))
        if burst_trigger:
            self._burst_ts.append(ts_ms)
        while self._burst_ts and self._burst_ts[0] < ts_ms - 2000:
            self._burst_ts.popleft()
        burst_cluster_score = min(1.0, len(self._burst_ts) / 5.0)

        impact_per_volume = abs(impact)
        recovery_slope = 0.0
        if len(self._depth_history) >= 8:
            p_now = self._depth_history[-1][3]
            p_prev = self._depth_history[-8][3]
            dt_s = max(1e-3, (self._depth_history[-1][0] - self._depth_history[-8][0]) / 1000.0)
            recovery_slope = (p_now - p_prev) / dt_s

        liquidity_resilience_score = max(
            0.0,
            min(
                1.0,
                (min(2.0, refill_rate) * 0.35)
                + (min(1.0, queue_refill_rate / max(queue_depletion_rate + 1e-9, 1e-9)) * 0.35)
                + (max(0.0, 1.0 - spread_bps / 20.0) * 0.30),
            ),
        )

        cross_venue_spread_divergence_bps = float(sequence.get("cross_venue_spread_divergence_bps", 0.0))
        stale_quote_score = float(sequence.get("stale_quote_score", 0.0))
        hedge_sync_score = float(sequence.get("hedge_sync_score", 0.0))

        liquidity_present = visible_liquidity > 0.0
        impact_measurable = abs(one.price_change) > 0.0 and one.total_volume > 0.0
        liquidity_regime_clear = (
            abs(book_depth_imbalance) > 0.08 or depth_collapse_ratio > 0.10 or refill_rate > 1.05
        )

        return MicrostructureFeatures(
            symbol=symbol,
            ts_ms=ts_ms,
            ref_price=ref_price,
            windows=windows,
            imbalance=imbalance,
            book_top_imbalance=book_top_imbalance,
            book_depth_imbalance=book_depth_imbalance,
            liquidity_gap_bps=liquidity_gap_bps,
            order_book_slope=order_book_slope,
            refill_rate=refill_rate,
            refill_velocity=refill_velocity,
            depletion_rate=depletion_rate,
            imbalance_shift=imbalance_shift,
            consumed_liquidity=consumed_liquidity,
            depth_collapse_ratio=depth_collapse_ratio,
            queue_depletion_rate=queue_depletion_rate,
            queue_refill_rate=queue_refill_rate,
            add_volume_rate=add_volume_rate,
            cancel_volume_rate=cancel_volume_rate,
            sweep_to_refill_ratio=sweep_to_refill_ratio,
            refill_latency_ms=refill_latency_ms,
            aggression_velocity=aggression_velocity,
            trade_intensity=trade_intensity,
            signed_flow_z=signed_flow_z,
            burst_cluster_score=burst_cluster_score,
            impact=impact,
            impact_per_volume=impact_per_volume,
            absorption=absorption,
            recovery_slope=recovery_slope,
            liquidity_resilience_score=liquidity_resilience_score,
            impact_persistence=impact_persistence,
            reversal_probability=reversal_probability,
            cross_venue_spread_divergence_bps=cross_venue_spread_divergence_bps,
            stale_quote_score=stale_quote_score,
            hedge_sync_score=hedge_sync_score,
            spread_bps=spread_bps,
            visible_liquidity=visible_liquidity,
            liquidity_present=liquidity_present,
            impact_measurable=impact_measurable,
            liquidity_regime_clear=liquidity_regime_clear,
            latency_ms=latency_ms,
            sequence=sequence,
        )

    @staticmethod
    def _liquidity_gaps_bps(depth: DepthTop) -> float:
        if depth.mid <= 0:
            return 0.0
        bid_gaps = []
        ask_gaps = []
        for i in range(1, min(len(depth.bids), 20)):
            bid_gaps.append(abs(depth.bids[i - 1][0] - depth.bids[i][0]))
        for i in range(1, min(len(depth.asks), 20)):
            ask_gaps.append(abs(depth.asks[i][0] - depth.asks[i - 1][0]))
        raw = max(bid_gaps + ask_gaps) if (bid_gaps or ask_gaps) else 0.0
        return (raw / depth.mid) * 10000.0

    @staticmethod
    def _book_slope(depth: DepthTop) -> float:
        def _slope(levels: list[tuple[float, float]]) -> float:
            if len(levels) < 3:
                return 0.0
            n = min(20, len(levels))
            x = list(range(1, n + 1))
            y = [levels[i - 1][1] for i in x]
            x_mean = sum(x) / n
            y_mean = sum(y) / n
            num = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
            den = sum((x[i] - x_mean) ** 2 for i in range(n))
            return num / den if den > 0 else 0.0

        return _slope(depth.bids) - _slope(depth.asks)


class EventDetector:
    """Detects liquidity-participant events and tracks impact decay curves."""

    def __init__(
        self,
        min_sweep_imbalance: float,
        min_sweep_price_move_bps: float,
        min_burst_volume: float,
        absorption_min_volume: float,
        absorption_max_move_bps: float,
        min_refill_rate_for_failure: float = 0.75,
        max_refill_rate_for_continuation: float = 0.35,
    ):
        self.min_sweep_imbalance = min_sweep_imbalance
        self.min_sweep_price_move_bps = min_sweep_price_move_bps
        self.min_burst_volume = min_burst_volume
        self.absorption_min_volume = absorption_min_volume
        self.absorption_max_move_bps = absorption_max_move_bps
        self.min_refill_rate_for_failure = min_refill_rate_for_failure
        self.max_refill_rate_for_continuation = max_refill_rate_for_continuation
        self._events: deque[DetectedEvent] = deque(maxlen=64)
        self._active_events: deque[dict[str, float | str | bool]] = deque(maxlen=64)
        self._impact_profiles: deque[dict[str, float]] = deque(maxlen=64)
        self._prev_state: str = "neutral|stable|neutral"

    @staticmethod
    def _state(features: MicrostructureFeatures) -> str:
        if features.signed_flow_z > 1.0 and features.burst_cluster_score > 0.3:
            flow = "forced_buy"
        elif features.signed_flow_z < -1.0 and features.burst_cluster_score > 0.3:
            flow = "forced_sell"
        else:
            flow = "neutral"

        if features.queue_depletion_rate > features.queue_refill_rate * 1.15 and features.depth_collapse_ratio > 0.08:
            book = "depleting"
        elif features.queue_refill_rate > features.queue_depletion_rate * 1.10:
            book = "refilling"
        else:
            book = "stable"

        if features.reversal_probability > 0.55:
            response = "reversal"
        elif features.impact_persistence > 0.25:
            response = "continuation"
        elif features.absorption > 1.0 and features.impact_per_volume < 1e-4:
            response = "absorption"
        else:
            response = "neutral"
        return f"{flow}|{book}|{response}"

    def detect(self, features: MicrostructureFeatures) -> list[DetectedEvent]:
        events: list[DetectedEvent] = []
        one = features.windows[1]
        five = features.windows[5]
        self._update_decay_curves(features.ts_ms, features.ref_price)
        cur_state = self._state(features)
        transition = f"{self._prev_state}->{cur_state}"

        move_bps = 0.0
        if one.vwap > 0:
            move_bps = (one.price_change / one.vwap) * 10000.0

        burst = one.total_volume >= self.min_burst_volume
        sweep = (
            burst
            and abs(features.imbalance) >= self.min_sweep_imbalance
            and abs(move_bps) >= self.min_sweep_price_move_bps
            and features.depth_collapse_ratio > 0.10
        )

        if sweep:
            side = "buy" if features.imbalance > 0 else "sell"
            ev = self._new_event("liquidity_sweep", features, abs(features.impact), side)
            events.append(ev)
            self._register_active_event(ev, features.ref_price, side)

        absorption_move_bps = 0.0
        if five.vwap > 0:
            absorption_move_bps = abs((five.price_change / five.vwap) * 10000.0)

        absorption = (
            five.total_volume >= self.absorption_min_volume
            and absorption_move_bps <= self.absorption_max_move_bps
            and features.refill_rate >= 0.95
        )
        if absorption:
            side = "sell" if five.sell_volume > five.buy_volume else "buy"
            events.append(self._new_event("absorption", features, features.absorption, side))

        vacuum = (
            one.total_volume <= max(0.4, self.min_burst_volume * 0.6)
            and features.visible_liquidity > 0.0
            and features.visible_liquidity < 3.0
            and abs(move_bps) >= self.min_sweep_price_move_bps
        )
        if vacuum:
            side = "buy" if move_bps > 0 else "sell"
            events.append(self._new_event("liquidity_vacuum", features, abs(move_bps), side))

        failed = self._detect_failed_breakout(features, move_bps)
        if failed is not None:
            events.append(failed)

        # State-transition event layer (microstructure-driven, not OHLCV thresholding).
        if transition.endswith("->forced_buy|depleting|continuation"):
            events.append(self._new_event("forced_flow_continuation", features, max(0.0, features.impact_persistence), "buy"))
        if transition.endswith("->forced_sell|depleting|continuation"):
            events.append(self._new_event("forced_flow_continuation", features, max(0.0, features.impact_persistence), "sell"))

        if "forced_buy|depleting" in transition and cur_state.endswith("refilling|reversal"):
            events.append(self._new_event("absorption_reversal", features, max(0.0, features.reversal_probability), "buy"))
        if "forced_sell|depleting" in transition and cur_state.endswith("refilling|reversal"):
            events.append(self._new_event("absorption_reversal", features, max(0.0, features.reversal_probability), "sell"))

        if cur_state.startswith("forced_buy|depleting") and features.refill_latency_ms > 300.0:
            events.append(self._new_event("queue_failure_breakout", features, max(0.0, features.sweep_to_refill_ratio), "buy"))
        if cur_state.startswith("forced_sell|depleting") and features.refill_latency_ms > 300.0:
            events.append(self._new_event("queue_failure_breakout", features, max(0.0, features.sweep_to_refill_ratio), "sell"))

        if features.burst_cluster_score > 0.5 and features.impact_persistence < 0.10 and features.reversal_probability > 0.5:
            side = "buy" if features.signed_flow_z < 0 else "sell"
            events.append(self._new_event("inventory_unwind", features, max(0.0, features.reversal_probability), side))

        if (
            abs(features.cross_venue_spread_divergence_bps) > 1.5
            and features.stale_quote_score > 0.4
            and features.hedge_sync_score > 0.4
        ):
            side = "buy" if features.cross_venue_spread_divergence_bps > 0 else "sell"
            events.append(self._new_event("cross_venue_arbitrage", features, abs(features.cross_venue_spread_divergence_bps), side))

        self._events.extend(events)
        self._prev_state = cur_state
        return events

    def sequence_state(self, now_ms: int) -> dict[str, float]:
        recent = [e for e in self._events if e.ts_ms >= now_ms - 6000]
        sweeps = [e for e in recent if e.event_type == "liquidity_sweep"]

        consecutive_sweeps = 0
        sweep_gap_ms = 0.0
        if len(sweeps) >= 2:
            consecutive_sweeps = len(sweeps)
            sweep_gap_ms = float(sweeps[-1].ts_ms - sweeps[-2].ts_ms)

        impact_decay = 1.0
        if len(sweeps) >= 2:
            prev = max(abs(sweeps[-2].strength), 1e-9)
            impact_decay = abs(sweeps[-1].strength) / prev

        impact_persistence = 0.0
        reversal_probability = 0.0
        if self._impact_profiles:
            vals = list(self._impact_profiles)[-12:]
            impact_persistence = sum(v.get("impact_persistence", 0.0) for v in vals) / len(vals)
            reversal_probability = sum(v.get("reversal_probability", 0.0) for v in vals) / len(vals)

        return {
            "consecutive_sweeps": float(consecutive_sweeps),
            "time_between_sweeps_ms": float(sweep_gap_ms),
            "impact_decay": float(impact_decay),
            "impact_persistence": float(impact_persistence),
            "reversal_probability": float(reversal_probability),
        }

    @staticmethod
    def _event_semantics(event_type: str, sweep_side: str) -> dict[str, str]:
        direction = "long" if sweep_side == "buy" else "short"
        if event_type == "liquidity_sweep":
            return {
                "trigger": "aggressor_flow_consumes_visible_book_and_displaces_price",
                "direction": direction,
                "expected_participant_behavior": "liquidity_takers_chase_and_market_makers_reprice",
                "who_loses": "late_takers_if_refill_appears_and_impact_fades",
            }
        if event_type == "absorption":
            return {
                "trigger": "high_traded_volume_with_low_price_progress_and_refill",
                "direction": "short" if sweep_side == "buy" else "long",
                "expected_participant_behavior": "passive_liquidity_absorbs_pressure_then_reverts",
                "who_loses": "aggressors_trapped_against_defended_liquidity",
            }
        if event_type == "liquidity_vacuum":
            return {
                "trigger": "thin_depth_with_price_jump_and_low_resistance",
                "direction": direction,
                "expected_participant_behavior": "small_flow_causes_oversized_move_until_liquidity_reforms",
                "who_loses": "mean_reversion_entries_before_liquidity_normalizes",
            }
        if event_type == "failed_breakout":
            return {
                "trigger": "prior_sweep_fails_after_refill_and_reversal_response",
                "direction": "short" if sweep_side == "buy" else "long",
                "expected_participant_behavior": "breakout_chasers_exit_into_reversal",
                "who_loses": "breakout_participants_entering_after_exhaustion",
            }
        if event_type == "forced_flow_continuation":
            return {
                "trigger": "forced_aggressor_flow_with_book_depletion_and_persistent_impact",
                "direction": direction,
                "expected_participant_behavior": "forced_flow_continues_before_replenishment",
                "who_loses": "liquidity_providers_and_late_contrarians",
            }
        if event_type == "absorption_reversal":
            return {
                "trigger": "depletion_state_transitions_to_refill_with_reversal_response",
                "direction": "short" if sweep_side == "buy" else "long",
                "expected_participant_behavior": "aggressor_exhausts_then_passive_side_reverts_price",
                "who_loses": "late_continuation_entries",
            }
        if event_type == "queue_failure_breakout":
            return {
                "trigger": "queue_depletion_persists_and_refill_latency_stays_elevated",
                "direction": direction,
                "expected_participant_behavior": "thin_queue_fails_to_rebuild_and_breakout_extends",
                "who_loses": "passive_quotes_left_unhedged",
            }
        if event_type == "inventory_unwind":
            return {
                "trigger": "burst_cluster_exhaustion_followed_by_impact_decay_and_reversal",
                "direction": "short" if sweep_side == "buy" else "long",
                "expected_participant_behavior": "dealer_inventory_rebalancing_reverts_move",
                "who_loses": "late_aggressors_after_exhaustion",
            }
        if event_type == "cross_venue_arbitrage":
            return {
                "trigger": "cross_venue_spread_divergence_with_stale_quote_and_fast_hedge_sync",
                "direction": direction,
                "expected_participant_behavior": "fast_router_hits_stale_venue_and_hedges_other_venue",
                "who_loses": "stale_quote_posters",
            }
        return {
            "trigger": "unknown",
            "direction": direction,
            "expected_participant_behavior": "unknown",
            "who_loses": "unknown",
        }

    @staticmethod
    def _new_event(
        event_type: str,
        features: MicrostructureFeatures,
        strength: float,
        sweep_side: str,
    ) -> DetectedEvent:
        semantics = EventDetector._event_semantics(event_type, sweep_side)
        return DetectedEvent(
            event_type=event_type,
            symbol=features.symbol,
            ts_ms=features.ts_ms,
            strength=float(strength),
            payload={
                "event_semantics": semantics,
                "imbalance": float(features.imbalance),
                "book_depth_imbalance": float(features.book_depth_imbalance),
                "book_top_imbalance": float(features.book_top_imbalance),
                "impact": float(features.impact),
                "absorption": float(features.absorption),
                "consumed_liquidity": float(features.consumed_liquidity),
                "refill_rate": float(features.refill_rate),
                "refill_velocity": float(features.refill_velocity),
                "depletion_rate": float(features.depletion_rate),
                "liquidity_gap_bps": float(features.liquidity_gap_bps),
                "order_book_slope": float(features.order_book_slope),
                "depth_collapse_ratio": float(features.depth_collapse_ratio),
                "impact_persistence": float(features.impact_persistence),
                "reversal_probability": float(features.reversal_probability),
                "liquidity_present": bool(features.liquidity_present),
                "impact_measurable": bool(features.impact_measurable),
                "sweep_side": sweep_side,
                "spread_bps": float(features.spread_bps),
                "latency_ms": float(features.latency_ms),
                "queue_depletion_rate": float(features.queue_depletion_rate),
                "queue_refill_rate": float(features.queue_refill_rate),
                "add_volume_rate": float(features.add_volume_rate),
                "cancel_volume_rate": float(features.cancel_volume_rate),
                "sweep_to_refill_ratio": float(features.sweep_to_refill_ratio),
                "refill_latency_ms": float(features.refill_latency_ms),
                "signed_flow_z": float(features.signed_flow_z),
                "burst_cluster_score": float(features.burst_cluster_score),
                "impact_per_volume": float(features.impact_per_volume),
                "recovery_slope": float(features.recovery_slope),
                "liquidity_resilience_score": float(features.liquidity_resilience_score),
                "cross_venue_spread_divergence_bps": float(features.cross_venue_spread_divergence_bps),
                "stale_quote_score": float(features.stale_quote_score),
                "hedge_sync_score": float(features.hedge_sync_score),
            },
        )

    def _register_active_event(self, event: DetectedEvent, price: float, side: str) -> None:
        self._active_events.append(
            {
                "event_type": event.event_type,
                "start_ts_ms": float(event.ts_ms),
                "start_price": float(price),
                "side": side,
                "p1": 0.0,
                "p5": 0.0,
                "p10": 0.0,
                "done": False,
            }
        )

    def _update_decay_curves(self, now_ms: int, price: float) -> None:
        if price <= 0:
            return
        for item in self._active_events:
            if bool(item.get("done", False)):
                continue
            dt = float(now_ms - float(item["start_ts_ms"]))
            if dt >= 1000 and float(item.get("p1", 0.0)) <= 0.0:
                item["p1"] = price
            if dt >= 5000 and float(item.get("p5", 0.0)) <= 0.0:
                item["p5"] = price
            if dt >= 10000 and float(item.get("p10", 0.0)) <= 0.0:
                item["p10"] = price

            if float(item.get("p10", 0.0)) > 0.0:
                p0 = max(float(item["start_price"]), 1e-9)
                p1 = float(item.get("p1", p0) or p0)
                p5 = float(item.get("p5", p1) or p1)
                p10 = float(item.get("p10", p5) or p5)
                side = str(item.get("side", "buy"))
                sign = 1.0 if side == "buy" else -1.0
                r1 = sign * ((p1 / p0) - 1.0)
                r5 = sign * ((p5 / p0) - 1.0)
                r10 = sign * ((p10 / p0) - 1.0)
                impact_persistence = max(0.0, min(1.0, (r10 / max(abs(r1), 1e-9))))
                reversal_probability = 1.0 if r5 < 0.0 or r10 < 0.0 else 0.0
                self._impact_profiles.append(
                    {
                        "impact_persistence": float(impact_persistence),
                        "reversal_probability": float(reversal_probability),
                    }
                )
                item["done"] = True

    def _detect_failed_breakout(
        self,
        features: MicrostructureFeatures,
        move_bps: float,
    ) -> DetectedEvent | None:
        recent_sweeps = [
            e for e in self._events
            if e.event_type == "liquidity_sweep" and (features.ts_ms - e.ts_ms) <= 2500
        ]
        if not recent_sweeps:
            return None
        last = recent_sweeps[-1]
        sweep_side = str(last.payload.get("sweep_side", "buy"))
        strong_refill = features.refill_rate >= self.min_refill_rate_for_failure
        reversal_hint = (
            (sweep_side == "buy" and move_bps <= 0.0)
            or (sweep_side == "sell" and move_bps >= 0.0)
            or features.reversal_probability > 0.5
        )
        if not strong_refill or not reversal_hint:
            return None
        strength = max(features.refill_rate - 1.0, features.reversal_probability)
        return self._new_event("failed_breakout", features, float(strength), sweep_side)
