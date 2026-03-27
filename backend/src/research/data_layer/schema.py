from __future__ import annotations

from dataclasses import dataclass


MICRO_ORDERBOOK = "micro_orderbook"
MICRO_TRADES = "micro_trades"
DERIV_FUNDING = "deriv_funding"
DERIV_OPEN_INTEREST = "deriv_open_interest"
DERIV_BASIS = "deriv_basis"
EVENT_LIQUIDATIONS = "event_liquidations"
EVENT_VOL_SHOCK = "event_vol_shock"
CROSS_ASSET_CLOSE = "cross_asset_close"


@dataclass(frozen=True)
class SourceConfig:
    symbol: str
    interval: str
    lookback_hours: int


@dataclass(frozen=True)
class ValidationThresholds:
    max_missing_ratio: float = 0.02
    max_timestamp_gap_factor: float = 3.0
    max_alignment_lag_seconds: int = 120


@dataclass(frozen=True)
class UnivariateThresholds:
    min_trades: int = 50
    min_t_stat: float = 2.0
    min_sharpe: float = 1.0
