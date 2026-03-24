from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import List, Tuple


# =========================
# DATA STRUCTURES
# =========================


@dataclass
class OrderBookSnapshot:
    bids: List[Tuple[float, float]]  # (price, size)
    asks: List[Tuple[float, float]]
    timestamp: float


@dataclass
class OrderBookFeatures:
    imbalance: float
    depth_imbalance: float
    slope: float
    spread: float
    top_liquidity: float
    refill_rate: float
    depletion_rate: float
    imbalance_shift: float


# =========================
# ORDERBOOK ENGINE
# =========================


class OrderBookEngine:
    def __init__(self, depth_levels: int = 20, history: int = 50):
        self.depth_levels = depth_levels

        self.prev_snapshot: OrderBookSnapshot | None = None
        self.snapshots: deque[OrderBookSnapshot] = deque(maxlen=history)

        self.prev_total_bid: float | None = None
        self.prev_total_ask: float | None = None
        self.prev_imbalance: float | None = None

    # =========================
    # CORE UPDATE
    # =========================

    def update(self, snapshot: OrderBookSnapshot) -> OrderBookFeatures:
        self.snapshots.append(snapshot)

        bids = snapshot.bids[: self.depth_levels]
        asks = snapshot.asks[: self.depth_levels]

        if not bids or not asks:
            self.prev_snapshot = snapshot
            self.prev_imbalance = 0.0
            # Return safe defaults when a side is empty.
            return OrderBookFeatures(
                imbalance=0.0,
                depth_imbalance=0.0,
                slope=0.0,
                spread=0.0,
                top_liquidity=0.0,
                refill_rate=0.0,
                depletion_rate=0.0,
                imbalance_shift=0.0,
            )

        bid_vol = sum(size for _, size in bids)
        ask_vol = sum(size for _, size in asks)

        # =========================
        # 1. IMBALANCE
        # =========================
        imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol + 1e-9)

        # =========================
        # 2. DEPTH IMBALANCE (TOP LEVELS)
        # =========================
        top_bid = sum(size for _, size in bids[:5])
        top_ask = sum(size for _, size in asks[:5])

        depth_imbalance = (top_bid - top_ask) / (top_bid + top_ask + 1e-9)

        # =========================
        # 3. SLOPE (LIQUIDITY DISTRIBUTION)
        # =========================
        def slope(side: List[Tuple[float, float]]) -> float:
            if len(side) < 2:
                return 0.0
            n = len(side)
            sum_x = 0.0
            sum_y = 0.0
            sum_xy = 0.0
            sum_x2 = 0.0
            for px, sz in side:
                x = float(px)
                y = float(sz)
                sum_x += x
                sum_y += y
                sum_xy += x * y
                sum_x2 += x * x
            den = (n * sum_x2) - (sum_x * sum_x)
            if abs(den) <= 1e-12:
                return 0.0
            return ((n * sum_xy) - (sum_x * sum_y)) / den

        slope_bid = slope(bids)
        slope_ask = slope(asks)
        slope_total = slope_bid - slope_ask

        # =========================
        # 4. SPREAD
        # =========================
        spread = asks[0][0] - bids[0][0]

        # =========================
        # 5. TOP LIQUIDITY
        # =========================
        top_liquidity = bids[0][1] + asks[0][1]

        # =========================
        # 6. QUEUE DYNAMICS
        # =========================
        refill_rate = 0.0
        depletion_rate = 0.0
        imbalance_shift = 0.0

        if self.prev_snapshot:
            prev_bids = self.prev_snapshot.bids[: self.depth_levels]
            prev_asks = self.prev_snapshot.asks[: self.depth_levels]

            prev_bid_vol = sum(size for _, size in prev_bids)
            prev_ask_vol = sum(size for _, size in prev_asks)

            delta_bid = bid_vol - prev_bid_vol
            delta_ask = ask_vol - prev_ask_vol

            refill_rate = max(delta_bid, 0.0) + max(delta_ask, 0.0)
            depletion_rate = abs(min(delta_bid, 0.0)) + abs(min(delta_ask, 0.0))

        if self.prev_imbalance is not None:
            imbalance_shift = imbalance - self.prev_imbalance

        # =========================
        # STORE STATE
        # =========================
        self.prev_snapshot = snapshot
        self.prev_imbalance = imbalance
        self.prev_total_bid = bid_vol
        self.prev_total_ask = ask_vol

        return OrderBookFeatures(
            imbalance=imbalance,
            depth_imbalance=depth_imbalance,
            slope=slope_total,
            spread=spread,
            top_liquidity=top_liquidity,
            refill_rate=refill_rate,
            depletion_rate=depletion_rate,
            imbalance_shift=imbalance_shift,
        )


@dataclass
class LiquidityResponse:
    absorbed: bool
    continued: bool
    vacuum: bool


class LiquidityAnalyzer:
    def __init__(self, vacuum_top_liquidity_threshold: float = 0.2):
        self.vacuum_top_liquidity_threshold = max(0.0, float(vacuum_top_liquidity_threshold))

    def evaluate(self, features: OrderBookFeatures, trade_pressure: float) -> LiquidityResponse:
        """
        trade_pressure > 0 = buy pressure
        trade_pressure < 0 = sell pressure
        """

        absorbed = (
            abs(trade_pressure) > 0.7
            and features.refill_rate > features.depletion_rate
        )

        continued = (
            abs(trade_pressure) > 0.7
            and features.depletion_rate > features.refill_rate
        )

        baseline_top_liquidity = 1.0
        normalized_top_liquidity = float(features.top_liquidity / max(baseline_top_liquidity, 1e-9))
        vacuum = (
            normalized_top_liquidity < self.vacuum_top_liquidity_threshold
            and features.depletion_rate > 0
        )

        return LiquidityResponse(
            absorbed=absorbed,
            continued=continued,
            vacuum=vacuum,
        )


class LiquidityEventEngine:
    def detect(self, features: OrderBookFeatures, response: LiquidityResponse) -> dict[str, bool]:
        # 1. SWEEP
        sweep = features.depletion_rate > features.refill_rate * 1.5

        # 2. ABSORPTION
        absorption = response.absorbed

        # 3. VACUUM
        vacuum = response.vacuum

        # 4. FAILED BREAKOUT
        failed = sweep and response.absorbed

        return {
            "sweep": sweep,
            "absorption": absorption,
            "vacuum": vacuum,
            "failed_breakout": failed,
        }


class LiquiditySignalEngine:
    def generate(self, events: dict[str, bool], features: OrderBookFeatures) -> str | None:
        # LONG: sell pressure failed
        if events["failed_breakout"] and features.imbalance > 0:
            return "LONG"

        # SHORT: buy pressure failed
        if events["failed_breakout"] and features.imbalance < 0:
            return "SHORT"

        # CONTINUATION
        if events["sweep"] and features.imbalance_shift > 0:
            return "LONG"

        if events["sweep"] and features.imbalance_shift < 0:
            return "SHORT"

        return None
