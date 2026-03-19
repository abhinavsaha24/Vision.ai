from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from backend.src.execution.circuit_breakers import (
    CircuitBreakerConfig,
    ExecutionCircuitBreaker,
)
from backend.src.execution.execution_engine import ExecutionEngine
from backend.src.exchange.exchange_adapter import PaperAdapter
from backend.src.features.indicators import FeatureEngineer
from backend.src.research.backtesting_engine import BacktestEngine
from backend.src.api.main import app


class _DummyStrategy:
    def generate_signal(self, df, prediction, regime=None):
        return 1


class _DummyRiskManager:
    def __init__(self):
        self.kill_switch_active = False
        self.events = []

    def activate_kill_switch(self, reason: str = ""):
        self.kill_switch_active = True

    def approve_trade(self, portfolio, trade_value, volatility=0.0, symbol="", trade_context=None):
        return {"approved": True, "reason": "ok", "adjustments": {}}

    def calculate_stop_loss(self, entry_price, side="long"):
        return entry_price * 0.99

    def calculate_trailing_stop(self, entry_price, highest_price, side="long"):
        return highest_price * 0.99

    def calculate_take_profit(self, entry_price, side="long"):
        return entry_price * 1.01


class _DummyPortfolio:
    def __init__(self, cash: float = 10_000.0):
        self.cash = cash
        self.positions = {}

    def get_portfolio(self):
        return {
            "cash": self.cash,
            "positions": self.positions,
            "equity_curve": [self.cash],
            "daily_pnl": 0,
            "open_trades": len(self.positions),
        }

    def open_position(self, symbol: str, quantity: float, price: float, side="long"):
        self.positions[symbol] = {
            "quantity": quantity,
            "entry_price": price,
            "side": side,
        }

    def close_position(self, symbol: str, price: float):
        self.positions.pop(symbol, None)


def _synthetic_ohlcv(n: int = 420) -> pd.DataFrame:
    idx = pd.date_range("2022-01-01", periods=n, freq="D", tz="UTC")
    trend = np.linspace(0, 25, n)
    noise = np.random.normal(0, 1.2, n)
    close = 100 + trend + np.cumsum(noise)
    open_ = close + np.random.normal(0, 0.4, n)
    high = np.maximum(open_, close) + np.abs(np.random.normal(0.8, 0.2, n))
    low = np.minimum(open_, close) - np.abs(np.random.normal(0.8, 0.2, n))
    volume = np.random.lognormal(mean=10.0, sigma=0.3, size=n)

    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=idx,
    )


def test_circuit_breaker_trips_on_stale_data():
    breaker = ExecutionCircuitBreaker(
        CircuitBreakerConfig(max_data_staleness_seconds=1)
    )

    stale_ts = datetime.now(timezone.utc) - timedelta(seconds=10)
    ok, reason = breaker.evaluate_data_freshness(stale_ts)

    assert ok is False
    assert reason == "stale_market_data"
    assert breaker.get_status()["tripped"] is True


def test_execution_engine_allows_stale_market_data_in_paper_mode():
    strategy = _DummyStrategy()
    risk = _DummyRiskManager()
    portfolio = _DummyPortfolio(cash=10_000)
    adapter = PaperAdapter(initial_cash=10_000, max_slippage=0.0)

    engine = ExecutionEngine(
        strategy_engine=strategy,
        risk_manager=risk,
        portfolio_manager=portfolio,
        adapter=adapter,
    )
    engine.circuit_breaker.config.max_data_staleness_seconds = 1

    stale_idx = pd.DatetimeIndex([datetime.now(timezone.utc) - timedelta(seconds=10)])
    df = pd.DataFrame(
        {
            "close": [100.0],
            "high": [101.0],
            "low": [99.0],
            "volatility_20": [0.01],
        },
        index=stale_idx,
    )

    out = engine.process_market_data(
        symbol="BTC/USDT",
        df=df,
        prediction={"probability": 0.6},
        price=100.0,
        regime={"trend": "uptrend"},
    )

    assert out["status"] != "DATA_STALE"
    assert risk.kill_switch_active is False


def test_walk_forward_retrain_validation_produces_windows():
    raw = _synthetic_ohlcv(480)
    fe = FeatureEngineer()
    df = fe.transform(raw, add_target=True, target_horizon=1).dropna()

    engine = BacktestEngine(initial_capital=100_000)
    out = engine.walk_forward_retrain_validation(df, n_splits=4)

    assert "error" not in out
    assert out["n_windows"] >= 1
    assert "avg_classification" in out
    assert "avg_trading" in out


def test_live_readiness_route_registered():
    paths = {getattr(r, "path") for r in app.router.routes if hasattr(r, "path")}
    assert "/live-trading/readiness" in paths
