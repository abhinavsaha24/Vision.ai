from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TradeTick:
    symbol: str
    price: float
    quantity: float
    exchange_ts_ms: int
    receive_ts_ms: int
    is_buyer_maker: bool

    @property
    def aggressor_side(self) -> str:
        # Binance `m=true` means buyer is maker -> sell aggressor.
        return "sell" if self.is_buyer_maker else "buy"


@dataclass(slots=True)
class DepthTop:
    symbol: str
    best_bid: float
    best_ask: float
    bid_qty: float
    ask_qty: float
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]
    exchange_ts_ms: int
    receive_ts_ms: int

    @property
    def spread(self) -> float:
        return max(0.0, self.best_ask - self.best_bid)

    @property
    def mid(self) -> float:
        if self.best_ask > 0 and self.best_bid > 0:
            return (self.best_ask + self.best_bid) / 2.0
        return 0.0


@dataclass(slots=True)
class WindowMetrics:
    window_seconds: int
    total_volume: float
    signed_volume: float
    buy_volume: float
    sell_volume: float
    trade_count: int
    price_change: float
    vwap: float


@dataclass(slots=True)
class MicrostructureFeatures:
    symbol: str
    ts_ms: int
    ref_price: float
    windows: dict[int, WindowMetrics]
    imbalance: float
    book_top_imbalance: float
    book_depth_imbalance: float
    liquidity_gap_bps: float
    order_book_slope: float
    refill_rate: float
    refill_velocity: float
    depletion_rate: float
    imbalance_shift: float
    consumed_liquidity: float
    depth_collapse_ratio: float
    queue_depletion_rate: float
    queue_refill_rate: float
    add_volume_rate: float
    cancel_volume_rate: float
    sweep_to_refill_ratio: float
    refill_latency_ms: float
    aggression_velocity: float
    trade_intensity: float
    signed_flow_z: float
    burst_cluster_score: float
    impact: float
    impact_per_volume: float
    absorption: float
    recovery_slope: float
    liquidity_resilience_score: float
    impact_persistence: float
    reversal_probability: float
    cross_venue_spread_divergence_bps: float
    stale_quote_score: float
    hedge_sync_score: float
    spread_bps: float
    visible_liquidity: float
    liquidity_present: bool
    impact_measurable: bool
    liquidity_regime_clear: bool
    latency_ms: float
    sequence: dict[str, float]


@dataclass(slots=True)
class DetectedEvent:
    event_type: str
    symbol: str
    ts_ms: int
    strength: float
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SignalDecision:
    symbol: str
    ts_ms: int
    side: str
    reason: str
    score: float
    event_type: str
    features: dict[str, float]


@dataclass(slots=True)
class RiskDecision:
    approved: bool
    reason: str
    quantity: float = 0.0
    notional: float = 0.0


@dataclass(slots=True)
class ExecutionReport:
    symbol: str
    ts_ms: int
    status: str
    side: str
    quantity: float
    requested_price: float
    fill_price: float
    slippage_bps: float
    fill_probability: float
    pnl: float = 0.0
    detail: str = ""
    requested_quantity: float = 0.0
    filled_quantity: float = 0.0
    simulated_latency_ms: float = 0.0


@dataclass(slots=True)
class EngineConfig:
    symbol: str = "BTCUSDT"
    use_depth_stream: bool = True
    queue_size: int = 5000
    max_signal_latency_ms: float = 1200.0
    max_event_staleness_ms: float = 2500.0
    max_spread_bps: float = 18.0
    min_visible_liquidity: float = 0.8
    min_sweep_imbalance: float = 0.55
    min_sweep_price_move_bps: float = 1.2
    min_burst_volume: float = 0.8
    absorption_min_volume: float = 1.2
    absorption_max_move_bps: float = 0.6
    min_refill_rate_for_failure: float = 0.75
    max_refill_rate_for_continuation: float = 0.35
    max_position_notional: float = 2500.0
    max_symbol_notional: float = 3500.0
    max_concurrent_trades: int = 1
    max_daily_trades: int = 400
    cooldown_after_loss_s: float = 30.0
    target_volatility_bps: float = 4.0
    execution_min_latency_ms: float = 8.0
    execution_max_latency_ms: float = 55.0
    execution_partial_fill_threshold: float = 0.18
    execution_partial_fill_min_ratio: float = 0.35
    performance_window: int = 400
    disable_min_trades: int = 80
    disable_min_expectancy: float = -0.1
    disable_min_sharpe: float = -0.2
    disable_max_drawdown: float = 200.0
    log_path: str = "data/live_alpha_signals.jsonl"
    max_round_trip_latency_ms: float = 180.0
    max_event_to_trade_ms: float = 220.0
    max_book_shift_bps: float = 2.5
    min_event_strength: float = 0.2
    disconnect_grace_ms: int = 2500
    max_daily_loss: float = 450.0
    circuit_breaker_loss_streak: int = 5
    processing_budget_ms: float = 4.5
    enable_cpu_affinity: bool = False
    cpu_cores: tuple[int, ...] = ()
    deployment_regions: tuple[str, ...] = ("tokyo", "singapore", "frankfurt")
    active_region: str = "tokyo"
