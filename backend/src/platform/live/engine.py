from __future__ import annotations

import asyncio
import logging
import time

from backend.src.platform.live.infrastructure import CpuAffinityManager
from backend.src.platform.live.infrastructure import InfrastructureConfig
from backend.src.platform.live.infrastructure import InfrastructureRuntime
from backend.src.platform.live.ingestion import BinanceWebSocketIngestor
from backend.src.platform.live.microstructure import EventDetector, MicrostructureEngine, SubSecondAggregator
from backend.src.platform.live.orderbook_intelligence import (
    LiquidityAnalyzer,
    LiquidityEventEngine,
    LiquiditySignalEngine,
    OrderBookEngine,
    OrderBookSnapshot,
)
from backend.src.platform.live.risk_execution import ExecutionEngine, RiskEngine
from backend.src.platform.live.signal import LatencyAwareFilter, SignalEngine
from backend.src.platform.live.telemetry import AsyncJsonlLogger, LiveValidationMonitor, build_log_payload
from backend.src.platform.live.types import (
    DepthTop,
    DetectedEvent,
    EngineConfig,
    ExecutionReport,
    MicrostructureFeatures,
    SignalDecision,
    TradeTick,
    WindowMetrics,
)

logger = logging.getLogger(__name__)


class RealTimeExecutionAlphaEngine:
    """Async low-latency event pipeline for live alpha generation and execution simulation."""

    def __init__(self, config: EngineConfig | None = None):
        self.config = config or EngineConfig()
        self.stop_event = asyncio.Event()

        self.trade_queue: asyncio.Queue[TradeTick] = asyncio.Queue(maxsize=self.config.queue_size)
        self.depth_queue: asyncio.Queue[DepthTop] = asyncio.Queue(maxsize=self.config.queue_size)
        self.metrics_queue: asyncio.Queue[tuple[TradeTick, dict[int, WindowMetrics], DepthTop | None]] = asyncio.Queue(maxsize=self.config.queue_size)
        self.feature_queue: asyncio.Queue[tuple[TradeTick, MicrostructureFeatures, list[DetectedEvent]]] = asyncio.Queue(maxsize=self.config.queue_size)

        self.ingestor = BinanceWebSocketIngestor(self.config.symbol, use_depth_stream=self.config.use_depth_stream)
        self.aggregator = SubSecondAggregator()
        self.micro = MicrostructureEngine()
        self.detector = EventDetector(
            min_sweep_imbalance=self.config.min_sweep_imbalance,
            min_sweep_price_move_bps=self.config.min_sweep_price_move_bps,
            min_burst_volume=self.config.min_burst_volume,
            absorption_min_volume=self.config.absorption_min_volume,
            absorption_max_move_bps=self.config.absorption_max_move_bps,
            min_refill_rate_for_failure=self.config.min_refill_rate_for_failure,
            max_refill_rate_for_continuation=self.config.max_refill_rate_for_continuation,
        )
        self.signal_engine = SignalEngine()
        self.orderbook_engine = OrderBookEngine(depth_levels=20, history=50)
        self.liquidity_analyzer = LiquidityAnalyzer()
        self.liquidity_event_engine = LiquidityEventEngine()
        self.liquidity_signal_engine = LiquiditySignalEngine()
        self.latency_filter = LatencyAwareFilter(
            max_signal_latency_ms=self.config.max_signal_latency_ms,
            max_event_staleness_ms=self.config.max_event_staleness_ms,
            max_spread_bps=self.config.max_spread_bps,
            min_visible_liquidity=self.config.min_visible_liquidity,
        )
        self.risk = RiskEngine(
            max_position_notional=self.config.max_position_notional,
            max_symbol_notional=self.config.max_symbol_notional,
            max_concurrent_trades=self.config.max_concurrent_trades,
            max_daily_trades=self.config.max_daily_trades,
            cooldown_after_loss_s=self.config.cooldown_after_loss_s,
            target_volatility_bps=self.config.target_volatility_bps,
        )
        self.execution = ExecutionEngine(
            min_latency_ms=self.config.execution_min_latency_ms,
            max_latency_ms=self.config.execution_max_latency_ms,
            partial_fill_threshold=self.config.execution_partial_fill_threshold,
            partial_fill_min_ratio=self.config.execution_partial_fill_min_ratio,
        )
        self.validation = LiveValidationMonitor(
            performance_window=self.config.performance_window,
            disable_min_trades=self.config.disable_min_trades,
            disable_min_expectancy=self.config.disable_min_expectancy,
            disable_min_sharpe=self.config.disable_min_sharpe,
            disable_max_drawdown=self.config.disable_max_drawdown,
        )
        self.logger = AsyncJsonlLogger(self.config.log_path)
        self.infrastructure = InfrastructureRuntime(
            InfrastructureConfig(
                max_round_trip_latency_ms=self.config.max_round_trip_latency_ms,
                max_event_to_trade_ms=self.config.max_event_to_trade_ms,
                max_book_shift_bps=self.config.max_book_shift_bps,
                min_event_strength=self.config.min_event_strength,
                disconnect_grace_ms=self.config.disconnect_grace_ms,
                max_daily_loss=self.config.max_daily_loss,
                circuit_breaker_loss_streak=self.config.circuit_breaker_loss_streak,
                processing_budget_ms=self.config.processing_budget_ms,
                enable_cpu_affinity=self.config.enable_cpu_affinity,
                cpu_cores=self.config.cpu_cores,
                deployment_regions=self.config.deployment_regions,
                active_region=self.config.active_region,
            )
        )

        self._depth_top: DepthTop | None = None
        self._tasks: list[asyncio.Task] = []
        self._last_mid_price: float | None = None
        self._event_outcome_horizons_s: tuple[int, ...] = (1, 5, 10, 30)
        self._pending_event_outcomes: list[dict[str, float | int | str]] = []
        self._pending_outcome_ttl_ms = 5 * 60 * 1000
        self._max_pending_outcomes = 20000

    async def start(self) -> None:
        if self.config.enable_cpu_affinity:
            await asyncio.to_thread(CpuAffinityManager.pin_current_process, self.config.cpu_cores)
        await self.logger.start()
        self._tasks = [
            asyncio.create_task(self.ingestor.run(self.trade_queue, self.depth_queue, self.stop_event)),
            asyncio.create_task(self._depth_consumer_loop()),
            asyncio.create_task(self._trade_processor_loop()),
            asyncio.create_task(self._feature_loop()),
            asyncio.create_task(self._signal_risk_execution_loop()),
            asyncio.create_task(self._infrastructure_metrics_loop()),
        ]

    async def stop(self) -> None:
        self.stop_event.set()
        self.ingestor.stop()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.logger.stop()

    async def run_forever(self) -> None:
        await self.start()
        try:
            while not self.stop_event.is_set():
                await asyncio.sleep(0.5)
        finally:
            await self.stop()

    async def _depth_consumer_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self._depth_top = await self.depth_queue.get()
                self.infrastructure.faults.on_depth_feed(self._depth_top.exchange_ts_ms)
                if self._depth_top.best_bid > 0 and self._depth_top.best_ask > 0:
                    self._last_mid_price = (self._depth_top.best_bid + self._depth_top.best_ask) / 2.0
                self.depth_queue.task_done()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("live_depth_loop_error err=%s", exc)

    async def _trade_processor_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                trade = await self.trade_queue.get()
                self.infrastructure.faults.on_trade_feed(trade.exchange_ts_ms)
                rtt_ms = max(0.0, float(trade.receive_ts_ms - trade.exchange_ts_ms))
                self.infrastructure.latency_monitor.on_rtt(rtt_ms)
                self.infrastructure.region_latency.update(self.config.active_region, rtt_ms)
                windows = self.aggregator.on_trade(trade)
                depth = self._depth_top
                await self.metrics_queue.put((trade, windows, depth))
                self.infrastructure.bus.publish_nowait("market_event", trade)
                self.trade_queue.task_done()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("live_trade_processor_error err=%s", exc)

    async def _feature_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                trade, windows_raw, depth = await self.metrics_queue.get()
                sequence = self.detector.sequence_state(trade.exchange_ts_ms)
                features = self.micro.compute(
                    symbol=trade.symbol,
                    ts_ms=trade.exchange_ts_ms,
                    windows=windows_raw,
                    depth=depth,
                    latency_ms=float(max(0, trade.receive_ts_ms - trade.exchange_ts_ms)),
                    sequence=sequence,
                )
                events = self.detector.detect(features)
                await self.feature_queue.put((trade, features, events))
                self.metrics_queue.task_done()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("live_feature_loop_error err=%s", exc)

    async def _signal_risk_execution_loop(self) -> None:
        while not self.stop_event.is_set():
            trade = None
            try:
                trade, features, events = await self.feature_queue.get()
                now_ms = int(time.time() * 1000)
                self._flush_event_outcomes(trade)

                if not self.validation.strategy_enabled:
                    self.logger.log_nowait(
                        {
                            "type": "event_decision",
                            "timestamp_ms": now_ms,
                            "symbol": trade.symbol,
                            "decision": "no_trade",
                            "reason": "strategy_disabled_validation_degraded",
                        }
                    )
                    continue

                can_trade, infra_reason = self.infrastructure.faults.allow_trading(now_ms)
                if not can_trade:
                    self.infrastructure.metrics.on_missed_opportunity()
                    self.logger.log_nowait(
                        {
                            "timestamp_ms": now_ms,
                            "symbol": trade.symbol,
                            "decision": "no_trade",
                            "reason": infra_reason,
                            "liquidity_diagnostics": {
                                "liquidity_present": bool(features.liquidity_present),
                                "refill_observed": bool(features.refill_rate >= 0.75),
                                "impact_persistent": bool(features.impact_persistence > 0.2),
                            },
                            "latency_ms": float(features.latency_ms),
                        }
                    )
                    continue

                if self.infrastructure.region_latency.reject(self.config.active_region):
                    self.infrastructure.metrics.on_missed_opportunity()
                    self.logger.log_nowait(
                        {
                            "timestamp_ms": now_ms,
                            "symbol": trade.symbol,
                            "decision": "no_trade",
                            "reason": "regional_latency_above_threshold",
                            "active_region": self.config.active_region,
                        }
                    )
                    continue

                for idx, event in enumerate(events):
                    event_id = self._event_id(event, idx)
                    expected_edge_bps = float(event.payload.get("expected_edge_bps", event.strength * 10.0))
                    ref_price = float(features.ref_price if features.ref_price > 0 else trade.price)

                    self._log_event_observation(
                        now_ms=now_ms,
                        trade=trade,
                        features=features,
                        event=event,
                        event_id=event_id,
                        expected_edge_bps=expected_edge_bps,
                        ref_price=ref_price,
                    )
                    self._schedule_event_outcomes(
                        event=event,
                        event_id=event_id,
                        side_hint=str(event.payload.get("sweep_side") or "buy"),
                        expected_edge_bps=expected_edge_bps,
                        ref_price=ref_price,
                    )

                    accepted, gate_reason = self.latency_filter.accepts(now_ms, event, features)
                    if not accepted:
                        self.infrastructure.metrics.on_missed_opportunity()
                        self.logger.log_nowait(
                            {
                                "type": "event_decision",
                                "timestamp_ms": now_ms,
                                "symbol": trade.symbol,
                                "event_id": event_id,
                                "event_type": event.event_type,
                                "decision": "rejected",
                                "reason": gate_reason,
                                "expected_edge_bps": expected_edge_bps,
                                "liquidity_diagnostics": {
                                    "liquidity_present": bool(features.liquidity_present),
                                    "refill_observed": bool(features.refill_rate >= 0.75),
                                    "impact_persistent": bool(features.impact_persistence > 0.2),
                                },
                                "features": {
                                    "spread_bps": float(features.spread_bps),
                                    "visible_liquidity": float(features.visible_liquidity),
                                    "latency_ms": float(features.latency_ms),
                                    "refill_rate": float(features.refill_rate),
                                    "book_depth_imbalance": float(features.book_depth_imbalance),
                                    "impact": float(features.impact),
                                    "impact_persistence": float(features.impact_persistence),
                                },
                            }
                        )
                        continue

                    observed_edge_bps = 0.0
                    if self._last_mid_price is not None and ref_price > 0:
                        observed_edge_bps = ((self._last_mid_price - ref_price) / ref_price) * 10000.0

                    pass_exec_gate, exec_gate_reason = self.infrastructure.execution_gate.evaluate(
                        now_ms=now_ms,
                        event_ts_ms=event.ts_ms,
                        event_strength=event.strength,
                        expected_edge_bps=expected_edge_bps,
                        observed_edge_bps=observed_edge_bps,
                    )
                    if not pass_exec_gate:
                        self.infrastructure.metrics.on_missed_opportunity()
                        self.logger.log_nowait(
                            {
                                "type": "event_decision",
                                "timestamp_ms": now_ms,
                                "symbol": trade.symbol,
                                "event_id": event_id,
                                "event_type": event.event_type,
                                "decision": "no_trade",
                                "reason": exec_gate_reason,
                                "expected_edge_bps": float(expected_edge_bps),
                                "observed_edge_bps": float(observed_edge_bps),
                            }
                        )
                        continue

                    signal = self.signal_engine.generate(event, features)
                    if signal is None:
                        signal = self._orderbook_signal_fallback(trade, features)
                    if signal is None:
                        self.infrastructure.metrics.on_missed_opportunity()
                        self.logger.log_nowait(
                            {
                                "type": "event_decision",
                                "timestamp_ms": now_ms,
                                "symbol": trade.symbol,
                                "event_id": event_id,
                                "event_type": event.event_type,
                                "decision": "no_trade",
                                "reason": "no_directional_asymmetry_or_execution_intent",
                                "expected_edge_bps": float(expected_edge_bps),
                                "event_semantics": event.payload.get("event_semantics", {}),
                            }
                        )
                        continue

                    self.infrastructure.bus.publish_nowait("signal", signal)

                    realized_vol_bps = self._realized_vol_bps(features)
                    risk_decision = self.risk.evaluate(
                        now_ms=now_ms,
                        signal=signal,
                        price=trade.price,
                        realized_vol_bps=realized_vol_bps,
                        current_position=self.execution.get_position(signal.symbol),
                    )
                    if not risk_decision.approved:
                        execution = ExecutionReport(
                            symbol=signal.symbol,
                            ts_ms=now_ms,
                            status="risk_rejected",
                            side=signal.side,
                            quantity=0.0,
                            requested_price=trade.price,
                            fill_price=0.0,
                            slippage_bps=0.0,
                            fill_probability=0.0,
                            detail=risk_decision.reason,
                        )
                        metrics = self.validation.metrics()
                        self.logger.log_nowait(
                            build_log_payload(
                                signal,
                                execution,
                                metrics,
                                risk_decision.reason,
                                event_context={
                                    "event_id": event_id,
                                    "event_type": event.event_type,
                                    "event_ts_ms": int(event.ts_ms),
                                    "expected_edge_bps": float(expected_edge_bps),
                                },
                            )
                        )
                        continue

                    had_position = self.execution.position is not None
                    exec_start_ns = time.perf_counter_ns()
                    execution = self.execution.execute(
                        now_ms=now_ms,
                        signal=signal,
                        quantity=risk_decision.quantity,
                        price=trade.price,
                        spread_bps=features.spread_bps,
                        visible_liquidity=features.visible_liquidity,
                    )

                    if execution.status == "opened" and not had_position:
                        self.risk.on_new_position(symbol=signal.symbol, notional=risk_decision.notional)
                    if execution.status == "scaled":
                        self.risk.on_new_position(symbol=signal.symbol, notional=risk_decision.notional)
                    if execution.status in {"closed", "partial_close"}:
                        self.risk.on_position_closed(
                            execution.pnl,
                            now_ms,
                            symbol=signal.symbol,
                            closed_notional=float(execution.quantity * max(0.0, execution.fill_price)),
                        )
                        self.infrastructure.faults.on_execution(execution.pnl)

                    elapsed_ms = (time.perf_counter_ns() - exec_start_ns) / 1_000_000.0
                    self.infrastructure.latency_monitor.on_pipeline(elapsed_ms)
                    self.infrastructure.metrics.on_execution(
                        latency_ms=float(max(0, execution.ts_ms - signal.ts_ms)),
                        slippage_bps=execution.slippage_bps,
                        success=execution.status in {"opened", "closed", "partial_close"},
                    )
                    self.infrastructure.bus.publish_nowait("execution", execution)

                    validation_metrics = self.validation.on_execution(execution)
                    self.logger.log_nowait(
                        build_log_payload(
                            signal,
                            execution,
                            validation_metrics,
                            gate_reason,
                            event_context={
                                "event_id": event_id,
                                "event_type": event.event_type,
                                "event_ts_ms": int(event.ts_ms),
                                "expected_edge_bps": float(expected_edge_bps),
                                "observed_edge_bps": float(observed_edge_bps),
                            },
                        )
                    )

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("live_signal_execution_loop_error err=%s", exc)
            finally:
                if trade is not None:
                    self.feature_queue.task_done()

    async def _infrastructure_metrics_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                await asyncio.sleep(1.0)
                now_ms = int(time.time() * 1000)
                can_trade, reason = self.infrastructure.faults.allow_trading(now_ms)
                if not can_trade:
                    self.logger.log_nowait(
                        {
                            "timestamp_ms": now_ms,
                            "type": "infra_guard",
                            "decision": "no_trade",
                            "reason": reason,
                        }
                    )

                snapshot = {
                    "timestamp_ms": now_ms,
                    "type": "infra_metrics",
                    "latency": self.infrastructure.latency_monitor.snapshot(),
                    "regional_latency": self.infrastructure.region_latency.snapshot(),
                    "execution": self.infrastructure.metrics.snapshot(),
                }
                self.logger.log_nowait(snapshot)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("infra_metrics_loop_error err=%s", exc)

    def _orderbook_signal_fallback(
        self,
        trade: TradeTick,
        features: MicrostructureFeatures,
    ) -> SignalDecision | None:
        depth = self._depth_top
        if depth is None or not depth.bids or not depth.asks:
            return None

        snapshot = OrderBookSnapshot(
            bids=[(float(p), float(q)) for p, q in depth.bids[:20]],
            asks=[(float(p), float(q)) for p, q in depth.asks[:20]],
            timestamp=float(depth.exchange_ts_ms) / 1000.0,
        )
        obf = self.orderbook_engine.update(snapshot)
        one = features.windows.get(1)
        if one is None:
            return None
        trade_pressure = float(one.signed_volume / max(one.total_volume, 1e-9))

        response = self.liquidity_analyzer.evaluate(obf, trade_pressure)
        events = self.liquidity_event_engine.detect(obf, response)
        raw_signal = self.liquidity_signal_engine.generate(events, obf)
        if raw_signal is None:
            return None

        side = "long" if raw_signal == "LONG" else "short"
        score = max(0.2, min(1.0, abs(obf.imbalance) + abs(obf.imbalance_shift)))
        return SignalDecision(
            symbol=trade.symbol,
            ts_ms=trade.exchange_ts_ms,
            side=side,
            reason="orderbook_participant_behavior",
            score=float(score),
            event_type="orderbook_liquidity",
            features={
                "ob_imbalance": float(obf.imbalance),
                "ob_depth_imbalance": float(obf.depth_imbalance),
                "ob_slope": float(obf.slope),
                "ob_spread": float(obf.spread),
                "ob_top_liquidity": float(obf.top_liquidity),
                "ob_refill_rate": float(obf.refill_rate),
                "ob_depletion_rate": float(obf.depletion_rate),
                "ob_imbalance_shift": float(obf.imbalance_shift),
                "trade_pressure": float(trade_pressure),
            },
        )

    @staticmethod
    def _realized_vol_bps(features: MicrostructureFeatures) -> float:
        ten = features.windows.get(10)
        if ten is None:
            return 0.0
        if ten.vwap <= 0:
            return 0.0
        return abs((ten.price_change / ten.vwap) * 10000.0)

    @staticmethod
    def _event_id(event: DetectedEvent, idx: int) -> str:
        return f"{event.symbol}:{event.ts_ms}:{event.event_type}:{idx}"

    def _schedule_event_outcomes(
        self,
        event: DetectedEvent,
        event_id: str,
        side_hint: str,
        expected_edge_bps: float,
        ref_price: float,
    ) -> None:
        if ref_price <= 0:
            return
        now_ms = int(time.time() * 1000)
        self._pending_event_outcomes = [
            p
            for p in self._pending_event_outcomes
            if int(p.get("created_at_ms", 0) or 0) + self._pending_outcome_ttl_ms >= now_ms
        ]
        side = str(side_hint or "buy").lower()
        for horizon in self._event_outcome_horizons_s:
            self._pending_event_outcomes.append(
                {
                    "event_id": event_id,
                    "symbol": event.symbol,
                    "event_type": event.event_type,
                    "event_ts_ms": int(event.ts_ms),
                    "target_ts_ms": int(event.ts_ms + (horizon * 1000)),
                    "horizon_s": int(horizon),
                    "side_hint": side,
                    "expected_edge_bps": float(expected_edge_bps),
                    "ref_price": float(ref_price),
                    "created_at_ms": now_ms,
                }
            )
        if len(self._pending_event_outcomes) > self._max_pending_outcomes:
            self._pending_event_outcomes = self._pending_event_outcomes[-self._max_pending_outcomes :]

    def _flush_event_outcomes(self, trade: TradeTick) -> None:
        if not self._pending_event_outcomes:
            return
        remaining: list[dict[str, float | int | str]] = []
        for pending in self._pending_event_outcomes:
            target_ts_ms = int(pending.get("target_ts_ms", 0) or 0)
            if trade.exchange_ts_ms < target_ts_ms:
                remaining.append(pending)
                continue

            ref_price = float(pending.get("ref_price", 0.0) or 0.0)
            if ref_price <= 0:
                continue
            raw_move_bps = ((trade.price - ref_price) / ref_price) * 10000.0
            side_hint = str(pending.get("side_hint") or "buy").lower()
            realized_edge_bps = raw_move_bps if side_hint == "buy" else -raw_move_bps
            expected_edge_bps = float(pending.get("expected_edge_bps", 0.0) or 0.0)

            self.logger.log_nowait(
                {
                    "type": "event_outcome",
                    "timestamp_ms": int(trade.exchange_ts_ms),
                    "symbol": str(pending.get("symbol", trade.symbol)),
                    "event_id": str(pending.get("event_id", "")),
                    "event_type": str(pending.get("event_type", "")),
                    "event_ts_ms": int(pending.get("event_ts_ms", 0) or 0),
                    "horizon_s": int(pending.get("horizon_s", 0) or 0),
                    "reference_price": float(ref_price),
                    "evaluation_price": float(trade.price),
                    "expected_edge_bps": expected_edge_bps,
                    "realized_edge_bps": float(realized_edge_bps),
                    "edge_delta_bps": float(realized_edge_bps - expected_edge_bps),
                }
            )
        self._pending_event_outcomes = remaining

    def _log_event_observation(
        self,
        now_ms: int,
        trade: TradeTick,
        features: MicrostructureFeatures,
        event: DetectedEvent,
        event_id: str,
        expected_edge_bps: float,
        ref_price: float,
    ) -> None:
        self.logger.log_nowait(
            {
                "type": "event_observation",
                "timestamp_ms": now_ms,
                "symbol": trade.symbol,
                "event_id": event_id,
                "event_type": event.event_type,
                "event_ts_ms": int(event.ts_ms),
                "event_strength": float(event.strength),
                "expected_edge_bps": float(expected_edge_bps),
                "reference_price": float(ref_price),
                "sweep_side_hint": str(event.payload.get("sweep_side", "")),
                "features": {
                    "imbalance": float(features.imbalance),
                    "book_top_imbalance": float(features.book_top_imbalance),
                    "book_depth_imbalance": float(features.book_depth_imbalance),
                    "spread_bps": float(features.spread_bps),
                    "visible_liquidity": float(features.visible_liquidity),
                    "refill_rate": float(features.refill_rate),
                    "impact": float(features.impact),
                    "impact_persistence": float(features.impact_persistence),
                    "latency_ms": float(features.latency_ms),
                },
            }
        )
