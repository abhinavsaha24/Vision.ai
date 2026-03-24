from __future__ import annotations

import asyncio
import math
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class VenueQuote:
    venue: str
    symbol: str
    bid: float
    ask: float
    bid_depth: float
    ask_depth: float
    latency_ms: float
    taker_fee_bps: float
    maker_fee_bps: float
    fill_probability: float
    timestamp_ms: int


@dataclass(slots=True)
class VenueOrderResult:
    venue: str
    symbol: str
    side: str
    quantity: float
    status: str
    requested_price: float
    fill_price: float
    filled_quantity: float
    fee_paid: float
    latency_ms: float
    order_id: str = ""
    detail: str = ""


@dataclass(slots=True)
class RoutedOrderPlan:
    venue: str
    side: str
    symbol: str
    quantity: float
    expected_price: float
    expected_slippage_bps: float
    expected_fee_bps: float
    expected_total_cost_bps: float


@dataclass(slots=True)
class ArbitrageOpportunity:
    symbol: str
    buy_venue: str
    sell_venue: str
    buy_price: float
    sell_price: float
    gross_edge_bps: float
    net_edge_bps: float
    max_size: float
    viability_score: float
    detected_ts_ms: int


@dataclass(slots=True)
class ArbitrageExecutionResult:
    status: str
    symbol: str
    buy_venue: str
    sell_venue: str
    requested_size: float
    executed_buy: float
    executed_sell: float
    net_pnl: float
    slippage_bps: float
    detail: str = ""


class VenueAdapter(Protocol):
    name: str

    async def get_quote(self, symbol: str) -> VenueQuote:
        ...

    async def place_market_order(self, symbol: str, side: str, quantity: float) -> VenueOrderResult:
        ...

    async def hedge_position(self, symbol: str, side: str, quantity: float) -> VenueOrderResult:
        ...


@dataclass(slots=True)
class MultiVenueConfig:
    min_net_edge_bps: float = 3.0
    max_latency_ms: float = 180.0
    max_quote_staleness_ms: float = 250.0
    max_book_shift_bps: float = 2.5
    max_exposure_per_venue: float = 5000.0
    max_total_exposure: float = 12000.0
    max_leg_timeout_ms: int = 220
    max_retries: int = 1
    circuit_breaker_failures: int = 6
    circuit_breaker_window_s: float = 30.0
    min_fill_probability: float = 0.70
    max_expected_slippage_bps: float = 2.6
    min_viability_score: float = 0.35
    diagnostics_path: str = "data/multi_venue_diagnostics.jsonl"


class SmartOrderRouter:
    def __init__(self, latency_weight_bps: float = 0.015):
        self.latency_weight_bps = latency_weight_bps

    def route(self, symbol: str, side: str, quantity: float, quotes: list[VenueQuote]) -> RoutedOrderPlan | None:
        if not quotes:
            return None

        candidates: list[RoutedOrderPlan] = []
        for q in quotes:
            if side == "buy":
                px = q.ask
                depth = q.ask_depth
            else:
                px = q.bid
                depth = q.bid_depth
            if px <= 0 or depth <= 0:
                continue

            participation = min(1.0, quantity / max(depth, 1e-9))
            slippage_bps = 0.35 + 1.8 * (participation ** 0.5)
            fee_bps = q.taker_fee_bps
            latency_penalty = q.latency_ms * self.latency_weight_bps
            total_cost_bps = slippage_bps + fee_bps + latency_penalty

            candidates.append(
                RoutedOrderPlan(
                    venue=q.venue,
                    side=side,
                    symbol=symbol,
                    quantity=quantity,
                    expected_price=px,
                    expected_slippage_bps=slippage_bps,
                    expected_fee_bps=fee_bps,
                    expected_total_cost_bps=total_cost_bps,
                )
            )

        if not candidates:
            return None

        if side == "buy":
            return min(candidates, key=lambda x: (x.expected_price, x.expected_total_cost_bps))
        return max(candidates, key=lambda x: (x.expected_price, -x.expected_total_cost_bps))


class ArbitrageDetector:
    def __init__(self, min_net_edge_bps: float):
        self.min_net_edge_bps = min_net_edge_bps

    def detect(self, symbol: str, quotes: list[VenueQuote]) -> ArbitrageOpportunity | None:
        if len(quotes) < 2:
            return None

        best_buy = min(quotes, key=lambda q: q.ask)
        best_sell = max(quotes, key=lambda q: q.bid)
        if best_buy.venue == best_sell.venue:
            return None
        if best_buy.ask <= 0 or best_sell.bid <= 0:
            return None

        gross_edge_bps = ((best_sell.bid - best_buy.ask) / best_buy.ask) * 10000.0
        total_fee_bps = best_buy.taker_fee_bps + best_sell.taker_fee_bps
        latency_penalty = (best_buy.latency_ms + best_sell.latency_ms) * 0.01
        fill_penalty = (1.0 - min(best_buy.fill_probability, best_sell.fill_probability)) * 2.5
        net_edge_bps = gross_edge_bps - total_fee_bps - latency_penalty - fill_penalty

        max_size = min(best_buy.ask_depth, best_sell.bid_depth)
        if max_size <= 0:
            return None
        if net_edge_bps < self.min_net_edge_bps:
            return None

        viability = max(0.0, min(1.0, net_edge_bps / max(self.min_net_edge_bps * 2.0, 1e-9)))
        return ArbitrageOpportunity(
            symbol=symbol,
            buy_venue=best_buy.venue,
            sell_venue=best_sell.venue,
            buy_price=best_buy.ask,
            sell_price=best_sell.bid,
            gross_edge_bps=gross_edge_bps,
            net_edge_bps=net_edge_bps,
            max_size=max_size,
            viability_score=viability,
            detected_ts_ms=int(time.time() * 1000),
        )


class LatencyOpportunityFilter:
    def __init__(self, config: MultiVenueConfig):
        self.config = config

    def should_trade(
        self,
        opportunity: ArbitrageOpportunity,
        buy_quote: VenueQuote,
        sell_quote: VenueQuote,
        detection_ts_ms: int,
    ) -> tuple[bool, str]:
        if buy_quote.latency_ms > self.config.max_latency_ms or sell_quote.latency_ms > self.config.max_latency_ms:
            return False, "latency_above_threshold"

        now_ms = int(time.time() * 1000)
        if now_ms - detection_ts_ms > self.config.max_quote_staleness_ms:
            return False, "opportunity_stale"

        book_shift = abs(((sell_quote.bid - buy_quote.ask) / max(buy_quote.ask, 1e-9)) * 10000.0 - opportunity.gross_edge_bps)
        if book_shift > self.config.max_book_shift_bps:
            return False, "book_changed"

        if opportunity.net_edge_bps < self.config.min_net_edge_bps:
            return False, "edge_decayed"

        return True, "ok"


class MultiVenueRiskController:
    def __init__(self, config: MultiVenueConfig):
        self.config = config
        self.venue_exposure: dict[str, float] = {}
        self.total_exposure: float = 0.0
        self.failure_times: list[float] = []
        self.circuit_open: bool = False

    def approve(self, opportunity: ArbitrageOpportunity, requested_size: float) -> tuple[bool, str, float]:
        if self.circuit_open:
            return False, "circuit_open", 0.0

        size = min(requested_size, opportunity.max_size)
        buy_notional = size * opportunity.buy_price
        sell_notional = size * opportunity.sell_price

        buy_exp = self.venue_exposure.get(opportunity.buy_venue, 0.0)
        sell_exp = self.venue_exposure.get(opportunity.sell_venue, 0.0)
        if buy_exp + buy_notional > self.config.max_exposure_per_venue:
            return False, "buy_venue_exposure_limit", 0.0
        if sell_exp + sell_notional > self.config.max_exposure_per_venue:
            return False, "sell_venue_exposure_limit", 0.0

        projected_total = self.total_exposure + buy_notional + sell_notional
        if projected_total > self.config.max_total_exposure:
            return False, "total_exposure_limit", 0.0

        return True, "approved", size

    def on_success(self, opportunity: ArbitrageOpportunity, size: float) -> None:
        buy_notional = size * opportunity.buy_price
        sell_notional = size * opportunity.sell_price
        self.venue_exposure[opportunity.buy_venue] = self.venue_exposure.get(opportunity.buy_venue, 0.0) + buy_notional
        self.venue_exposure[opportunity.sell_venue] = self.venue_exposure.get(opportunity.sell_venue, 0.0) + sell_notional
        self.total_exposure += buy_notional + sell_notional

    def on_position_closed(self, opportunity: ArbitrageOpportunity, size: float) -> None:
        buy_notional = max(0.0, size * opportunity.buy_price)
        sell_notional = max(0.0, size * opportunity.sell_price)
        self.venue_exposure[opportunity.buy_venue] = max(0.0, self.venue_exposure.get(opportunity.buy_venue, 0.0) - buy_notional)
        self.venue_exposure[opportunity.sell_venue] = max(0.0, self.venue_exposure.get(opportunity.sell_venue, 0.0) - sell_notional)
        self.total_exposure = max(0.0, self.total_exposure - (buy_notional + sell_notional))

    def on_failure(self) -> None:
        now = time.time()
        self.failure_times.append(now)
        cutoff = now - self.config.circuit_breaker_window_s
        self.failure_times = [t for t in self.failure_times if t >= cutoff]
        if len(self.failure_times) >= self.config.circuit_breaker_failures:
            self.circuit_open = True


class DiagnosticsRecorder:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    async def log(self, payload: dict) -> None:
        async with self._lock:
            line = json.dumps(payload, separators=(",", ":"), ensure_ascii=True) + "\n"
            await asyncio.to_thread(self._append, line)

    def _append(self, line: str) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line)


class ArbitrageExecutionCoordinator:
    def __init__(self, config: MultiVenueConfig):
        self.config = config

    async def execute(
        self,
        opportunity: ArbitrageOpportunity,
        size: float,
        venues: dict[str, VenueAdapter],
    ) -> ArbitrageExecutionResult:
        buy_v = venues[opportunity.buy_venue]
        sell_v = venues[opportunity.sell_venue]

        buy_task = asyncio.create_task(buy_v.place_market_order(opportunity.symbol, "buy", size))
        sell_task = asyncio.create_task(sell_v.place_market_order(opportunity.symbol, "sell", size))

        try:
            timeout_s = self.config.max_leg_timeout_ms / 1000.0
            buy_res, sell_res = await asyncio.wait_for(asyncio.gather(buy_task, sell_task), timeout=timeout_s)
        except Exception as exc:
            buy_task.cancel()
            sell_task.cancel()
            await asyncio.gather(buy_task, sell_task, return_exceptions=True)
            return ArbitrageExecutionResult(
                status="failed",
                symbol=opportunity.symbol,
                buy_venue=opportunity.buy_venue,
                sell_venue=opportunity.sell_venue,
                requested_size=size,
                executed_buy=0.0,
                executed_sell=0.0,
                net_pnl=0.0,
                slippage_bps=0.0,
                detail=f"coordination_timeout_or_error:{exc}",
            )

        return await self._finalize(opportunity, size, buy_res, sell_res, venues)

    async def _finalize(
        self,
        opportunity: ArbitrageOpportunity,
        size: float,
        buy_res: VenueOrderResult,
        sell_res: VenueOrderResult,
        venues: dict[str, VenueAdapter],
    ) -> ArbitrageExecutionResult:
        buy_fill = max(0.0, buy_res.filled_quantity)
        sell_fill = max(0.0, sell_res.filled_quantity)

        if buy_res.status != "filled" or sell_res.status != "filled":
            await self._hedge_unmatched(opportunity, buy_res, sell_res, venues)
            return ArbitrageExecutionResult(
                status="partial_or_failed",
                symbol=opportunity.symbol,
                buy_venue=opportunity.buy_venue,
                sell_venue=opportunity.sell_venue,
                requested_size=size,
                executed_buy=buy_fill,
                executed_sell=sell_fill,
                net_pnl=0.0,
                slippage_bps=0.0,
                detail="one_leg_failed_or_partial_hedged",
            )

        matched = min(buy_fill, sell_fill)
        gross_pnl = (sell_res.fill_price - buy_res.fill_price) * matched
        fees = buy_res.fee_paid + sell_res.fee_paid
        net_pnl = gross_pnl - fees

        expected_mid = (opportunity.buy_price + opportunity.sell_price) / 2.0
        realized_mid = (buy_res.fill_price + sell_res.fill_price) / 2.0
        slippage_bps = abs((realized_mid - expected_mid) / max(expected_mid, 1e-9)) * 10000.0

        return ArbitrageExecutionResult(
            status="filled",
            symbol=opportunity.symbol,
            buy_venue=opportunity.buy_venue,
            sell_venue=opportunity.sell_venue,
            requested_size=size,
            executed_buy=buy_fill,
            executed_sell=sell_fill,
            net_pnl=net_pnl,
            slippage_bps=slippage_bps,
            detail="ok",
        )

    async def _hedge_unmatched(
        self,
        opportunity: ArbitrageOpportunity,
        buy_res: VenueOrderResult,
        sell_res: VenueOrderResult,
        venues: dict[str, VenueAdapter],
    ) -> None:
        buy_fill = max(0.0, buy_res.filled_quantity)
        sell_fill = max(0.0, sell_res.filled_quantity)
        diff = buy_fill - sell_fill
        if abs(diff) <= 1e-9:
            return

        if diff > 0:
            try:
                await venues[opportunity.buy_venue].hedge_position(opportunity.symbol, "sell", diff)
            except Exception as exc:
                logger.error(
                    "hedge_unmatched_failed buy_venue=%s sell_venue=%s symbol=%s diff=%s err=%s",
                    opportunity.buy_venue,
                    opportunity.sell_venue,
                    opportunity.symbol,
                    diff,
                    exc,
                )
        else:
            try:
                await venues[opportunity.sell_venue].hedge_position(opportunity.symbol, "buy", abs(diff))
            except Exception as exc:
                logger.error(
                    "hedge_unmatched_failed buy_venue=%s sell_venue=%s symbol=%s diff=%s err=%s",
                    opportunity.buy_venue,
                    opportunity.sell_venue,
                    opportunity.symbol,
                    diff,
                    exc,
                )


class MultiVenueArbitrageEngine:
    def __init__(self, config: MultiVenueConfig, venues: list[VenueAdapter]):
        self.config = config
        self.venues = {v.name: v for v in venues}
        self.router = SmartOrderRouter()
        self.detector = ArbitrageDetector(min_net_edge_bps=config.min_net_edge_bps)
        self.filter = LatencyOpportunityFilter(config)
        self.risk = MultiVenueRiskController(config)
        self._risk_lock = asyncio.Lock()
        self.coordinator = ArbitrageExecutionCoordinator(config)
        self.diagnostics = DiagnosticsRecorder(config.diagnostics_path)

    def _execution_viable(
        self,
        opportunity: ArbitrageOpportunity,
        buy_q: VenueQuote,
        sell_q: VenueQuote,
        trade_size: float,
    ) -> tuple[bool, str, dict[str, float]]:
        min_fill = min(float(buy_q.fill_probability), float(sell_q.fill_probability))
        if min_fill < self.config.min_fill_probability:
            return False, "execution_quality_insufficient_fill_probability", {"min_fill_probability": min_fill}

        safe_size = max(0.0, float(trade_size))
        participation_buy = min(1.0, safe_size / max(buy_q.ask_depth, 1e-9))
        participation_sell = min(1.0, safe_size / max(sell_q.bid_depth, 1e-9))
        expected_slippage_bps = (0.35 + 1.8 * (participation_buy ** 0.5)) + (0.35 + 1.8 * (participation_sell ** 0.5))
        if expected_slippage_bps > self.config.max_expected_slippage_bps:
            return False, "execution_quality_insufficient_slippage", {"expected_slippage_bps": expected_slippage_bps}

        if float(opportunity.viability_score) < self.config.min_viability_score:
            return False, "execution_quality_insufficient_viability", {"viability_score": float(opportunity.viability_score)}

        return True, "ok", {
            "min_fill_probability": min_fill,
            "expected_slippage_bps": float(expected_slippage_bps),
            "viability_score": float(opportunity.viability_score),
        }

    async def collect_quotes(self, symbol: str) -> list[VenueQuote]:
        tasks = [asyncio.create_task(v.get_quote(symbol)) for v in self.venues.values()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        quotes: list[VenueQuote] = []
        for r in results:
            if isinstance(r, Exception):
                logger.warning("venue_quote_error err=%s", r)
                continue
            if isinstance(r, VenueQuote):
                quotes.append(r)
        return quotes

    async def run_cycle(self, symbol: str, requested_size: float) -> ArbitrageExecutionResult | None:
        if not math.isfinite(requested_size) or requested_size <= 0.0:
            await self.diagnostics.log(
                {
                    "ts_ms": int(time.time() * 1000),
                    "type": "no_trade",
                    "reason": "invalid_requested_size",
                    "symbol": symbol,
                    "requested_size": float(requested_size if math.isfinite(requested_size) else 0.0),
                }
            )
            return None

        quotes = await self.collect_quotes(symbol)
        if len(quotes) < 2:
            await self.diagnostics.log(
                {
                    "ts_ms": int(time.time() * 1000),
                    "type": "no_trade",
                    "reason": "insufficient_venues",
                    "symbol": symbol,
                }
            )
            return None

        opportunity = self.detector.detect(symbol, quotes)
        if opportunity is None:
            best_bid = max((q.bid for q in quotes), default=0.0)
            best_ask = min((q.ask for q in quotes), default=0.0)
            gross_edge_bps = ((best_bid - best_ask) / max(best_ask, 1e-9)) * 10000.0 if best_ask > 0 else 0.0
            await self.diagnostics.log(
                {
                    "ts_ms": int(time.time() * 1000),
                    "type": "no_trade",
                    "reason": "no_cross_venue_edge",
                    "symbol": symbol,
                    "diagnostics": {
                        "best_bid": float(best_bid),
                        "best_ask": float(best_ask),
                        "gross_edge_bps": float(gross_edge_bps),
                        "min_required_net_edge_bps": float(self.config.min_net_edge_bps),
                    },
                }
            )
            return None

        buy_q = next((q for q in quotes if q.venue == opportunity.buy_venue), None)
        sell_q = next((q for q in quotes if q.venue == opportunity.sell_venue), None)
        if buy_q is None or sell_q is None:
            return None

        ok, reason = self.filter.should_trade(opportunity, buy_q, sell_q, opportunity.detected_ts_ms)
        if not ok:
            await self.diagnostics.log(
                {
                    "ts_ms": int(time.time() * 1000),
                    "type": "no_trade",
                    "reason": reason,
                    "symbol": symbol,
                    "opportunity": {
                        "buy_venue": opportunity.buy_venue,
                        "sell_venue": opportunity.sell_venue,
                        "gross_edge_bps": opportunity.gross_edge_bps,
                        "net_edge_bps": opportunity.net_edge_bps,
                    },
                }
            )
            return None

        provisional_size = min(float(requested_size), float(opportunity.max_size))
        viable, viability_reason, quality = self._execution_viable(opportunity, buy_q, sell_q, provisional_size)
        if not viable:
            await self.diagnostics.log(
                {
                    "ts_ms": int(time.time() * 1000),
                    "type": "no_trade",
                    "reason": viability_reason,
                    "symbol": symbol,
                    "opportunity": {
                        "buy_venue": opportunity.buy_venue,
                        "sell_venue": opportunity.sell_venue,
                        "gross_edge_bps": float(opportunity.gross_edge_bps),
                        "net_edge_bps": float(opportunity.net_edge_bps),
                    },
                    "execution_quality": quality,
                }
            )
            return None

        async with self._risk_lock:
            approved, risk_reason, trade_size = self.risk.approve(opportunity, requested_size)
            if approved:
                # Reserve notional before sending both legs to avoid concurrent over-allocation.
                self.risk.on_success(opportunity, trade_size)
        if not approved:
            await self.diagnostics.log(
                {
                    "ts_ms": int(time.time() * 1000),
                    "type": "no_trade",
                    "reason": risk_reason,
                    "symbol": symbol,
                }
            )
            return None

        result = await self.coordinator.execute(opportunity, trade_size, self.venues)
        async with self._risk_lock:
            # Release reserved exposure after execution/hedging attempt completion.
            self.risk.on_position_closed(opportunity, trade_size)
            if result.status != "filled":
                self.risk.on_failure()

        await self.diagnostics.log(
            {
                "ts_ms": int(time.time() * 1000),
                "type": "arbitrage_execution",
                "symbol": symbol,
                "status": result.status,
                "detail": result.detail,
                "requested_size": result.requested_size,
                "executed_buy": result.executed_buy,
                "executed_sell": result.executed_sell,
                "net_pnl": result.net_pnl,
                "slippage_bps": result.slippage_bps,
                "fill_success_rate": (
                    (1.0 if result.executed_buy > 0 else 0.0)
                    + (1.0 if result.executed_sell > 0 else 0.0)
                ) / 2.0,
            }
        )

        return result

    async def smart_route_single_order(self, symbol: str, side: str, quantity: float) -> VenueOrderResult | None:
        if not math.isfinite(quantity) or quantity <= 0.0:
            return None
        quotes = await self.collect_quotes(symbol)
        plan = self.router.route(symbol, side, quantity, quotes)
        if plan is None:
            return None
        venue = self.venues.get(plan.venue)
        if venue is None:
            return None
        return await venue.place_market_order(symbol, side, quantity)
