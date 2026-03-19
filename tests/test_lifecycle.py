"""
Tests for the new infrastructure modules:
  - App import speed (no blocking at import time)
  - EventBus publish/subscribe
  - StateManager save/load round-trip
  - WorkerManager lifecycle
  - ModeManager transitions
  - PortfolioManager serialization
"""

import sys
import os
import asyncio
import time

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


# ==================================================
# App Import Test — verifies lifespan fix
# ==================================================

class TestAppImport:
    """Verify that importing main.py does NOT block or run heavy init."""

    def test_app_import_is_fast(self):
        """App module should import in under 5 seconds (no heavy init)."""
        start = time.time()
        from backend.src.api.main import app
        elapsed = time.time() - start

        assert elapsed < 5.0, f"App import took {elapsed:.1f}s — too slow, something is blocking"
        assert app is not None
        assert app.title == "Vision-AI Trading API"

    def test_app_has_lifespan(self):
        """App should use the lifespan context manager."""
        from backend.src.api.main import app
        # FastAPI stores lifespan as router.lifespan_context
        assert app.router.lifespan_context is not None

    def test_services_not_initialized_at_import(self):
        """Services should NOT be initialized until lifespan starts."""
        from backend.src.api.main import app
        # Before lifespan, app.state should not have services attribute
        # (or services should not be initialized)
        if hasattr(app.state, 'services'):
            assert not app.state.services.initialized


# ==================================================
# EventBus Tests
# ==================================================

class TestEventBus:

    def test_publish_subscribe(self):
        """Events should be delivered to subscribers."""
        from backend.src.core.event_bus import EventBus, EventType

        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(EventType.MARKET_DATA, handler)

        async def run():
            await bus.publish(EventType.MARKET_DATA, {"price": 50000})

        asyncio.run(run())
        assert len(received) == 1
        assert received[0].data["price"] == 50000

    def test_unsubscribe(self):
        """Unsubscribed handlers should not receive events."""
        from backend.src.core.event_bus import EventBus, EventType

        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(EventType.SIGNAL_GENERATED, handler)
        bus.unsubscribe(EventType.SIGNAL_GENERATED, handler)

        async def run():
            await bus.publish(EventType.SIGNAL_GENERATED, {"signal": "BUY"})

        asyncio.run(run())
        assert len(received) == 0

    def test_multiple_event_types(self):
        """Different event types should go to correct handlers."""
        from backend.src.core.event_bus import EventBus, EventType

        bus = EventBus()
        market_events = []
        trade_events = []

        async def market_handler(event):
            market_events.append(event)

        async def trade_handler(event):
            trade_events.append(event)

        bus.subscribe(EventType.MARKET_DATA, market_handler)
        bus.subscribe(EventType.TRADE_EXECUTED, trade_handler)

        async def run():
            await bus.publish(EventType.MARKET_DATA, {"price": 50000})
            await bus.publish(EventType.TRADE_EXECUTED, {"side": "buy"})

        asyncio.run(run())
        assert len(market_events) == 1
        assert len(trade_events) == 1

    def test_event_history(self):
        """Event history should be queryable."""
        from backend.src.core.event_bus import EventBus, EventType

        bus = EventBus()

        async def run():
            await bus.publish(EventType.RISK_ALERT, {"type": "drawdown"})
            await bus.publish(EventType.RISK_ALERT, {"type": "daily_loss"})

        asyncio.run(run())
        history = bus.get_recent_events(EventType.RISK_ALERT)
        assert len(history) == 2

    def test_metrics(self):
        """EventBus should track publish/deliver counts."""
        from backend.src.core.event_bus import EventBus, EventType

        bus = EventBus()

        async def handler(event):
            pass

        bus.subscribe(EventType.SYSTEM_STATUS, handler)

        async def run():
            await bus.publish(EventType.SYSTEM_STATUS, {"status": "ok"})

        asyncio.run(run())
        metrics = bus.get_metrics()
        assert metrics["published"] == 1
        assert metrics["delivered"] == 1


# ==================================================
# StateManager Tests
# ==================================================

class TestStateManager:

    def test_save_load_portfolio_via_cache(self):
        """Portfolio state should round-trip through in-memory cache."""
        from backend.src.core.cache import RedisCache
        from backend.src.core.state_manager import StateManager

        cache = RedisCache(enabled=False)  # in-memory fallback
        sm = StateManager(cache=cache)

        portfolio_data = {
            "cash": 95000.0,
            "current_equity": 98000.0,
            "unrealized_pnl": 3000.0,
            "realized_pnl": -2000.0,
            "open_trades": 2,
            "total_trades": 15,
            "win_rate": 0.6,
            "max_drawdown": 0.05,
        }

        assert sm.save_portfolio(portfolio_data)
        loaded = sm.load_portfolio()
        assert loaded is not None
        assert loaded["cash"] == 95000.0
        assert loaded["total_trades"] == 15

    def test_save_load_risk_state(self):
        """Risk state should round-trip through cache."""
        from backend.src.core.cache import RedisCache
        from backend.src.core.state_manager import StateManager

        cache = RedisCache(enabled=False)
        sm = StateManager(cache=cache)

        risk_data = {
            "kill_switch_active": True,
            "daily_loss": 0.03,
            "events": ["drawdown_breach"],
        }

        assert sm.save_risk_state(risk_data)
        loaded = sm.load_risk_state()
        assert loaded is not None
        assert loaded["kill_switch_active"] is True


# ==================================================
# ModeManager Tests
# ==================================================

class TestModeManager:

    def test_starts_in_simulation(self):
        from backend.src.core.mode_manager import ModeManager
        mm = ModeManager(initial_mode="simulation")
        assert mm.is_simulation
        assert not mm.is_live

    def test_paper_maps_to_simulation(self):
        from backend.src.core.mode_manager import ModeManager
        mm = ModeManager(initial_mode="paper")
        assert mm.is_simulation

    def test_can_always_go_to_research(self):
        from backend.src.core.mode_manager import ModeManager, TradingMode
        mm = ModeManager(initial_mode="simulation")
        result = mm.transition(TradingMode.RESEARCH)
        assert result["success"]
        assert mm.is_research

    def test_cannot_go_live_without_prereqs(self):
        from backend.src.core.mode_manager import ModeManager, TradingMode
        mm = ModeManager(initial_mode="simulation")
        check = mm.can_transition(TradingMode.LIVE)
        assert not check["allowed"]
        assert len(check["reasons"]) > 0

    def test_can_go_live_with_all_prereqs(self):
        from backend.src.core.mode_manager import ModeManager, TradingMode
        mm = ModeManager(initial_mode="simulation")
        mm.set_requirement("backtest_passed", True)
        mm.set_requirement("preflight_passed", True)
        mm.set_requirement("api_keys_valid", True)
        check = mm.can_transition(TradingMode.LIVE)
        assert check["allowed"]


# ==================================================
# PortfolioManager Serialization Tests
# ==================================================

class TestPortfolioSerialization:

    def test_to_dict_round_trip(self):
        from backend.src.portfolio.portfolio_manager import PortfolioManager
        pm = PortfolioManager(initial_cash=50000)

        data = pm.to_dict()
        assert data["initial_cash"] == 50000
        assert data["cash"] == 50000

        pm2 = PortfolioManager.from_dict(data)
        assert pm2.initial_cash == 50000
        assert pm2.cash == 50000

    def test_from_dict_preserves_state(self):
        from backend.src.portfolio.portfolio_manager import PortfolioManager
        data = {
            "initial_cash": 100000,
            "cash": 85000,
            "positions": {"BTC/USDT": {"size": 0.1, "entry_price": 50000}},
            "trade_history": [{"symbol": "BTC/USDT", "pnl": 500}],
            "equity_curve": [100000, 99000, 101000],
            "realized_pnl": 1500.0,
            "total_trades": 10,
            "winning_trades": 6,
        }

        pm = PortfolioManager.from_dict(data)
        assert pm.cash == 85000
        assert pm.total_trades == 10
        assert pm.winning_trades == 6
        assert len(pm.equity_curve) == 3


# ==================================================
# BaseStrategy Tests
# ==================================================

class TestBaseStrategy:

    def test_strategy_interface(self):
        from backend.src.strategy.base_strategy import BaseStrategy

        class TestStrat(BaseStrategy):
            def generate_signal(self, *args, **kwargs):
                return 1  # always long

        s = TestStrat(name="test", description="A test strategy")
        assert s.name == "test"
        assert s.generate_signal() == 1

    def test_performance_tracking(self):
        from backend.src.strategy.base_strategy import BaseStrategy

        class TestStrat(BaseStrategy):
            def generate_signal(self, *args, **kwargs):
                return 1

        s = TestStrat(name="test")
        s.generate_signal_with_tracking()
        s.generate_signal_with_tracking()

        assert s.performance.total_signals == 2
        assert s.performance.long_signals == 2

    def test_parameter_management(self):
        from backend.src.strategy.base_strategy import BaseStrategy

        class TestStrat(BaseStrategy):
            def __init__(self):
                super().__init__(name="param_test")
                self.threshold = 0.5
                self.register_parameter("threshold", 0.5, "Signal threshold", 0.0, 1.0)

            def generate_signal(self, *args, **kwargs):
                return 1 if kwargs.get("score", 0) > self.threshold else 0

        s = TestStrat()
        assert len(s.get_parameters()) == 1

        s.update_parameters({"threshold": 0.8})
        assert s.threshold == 0.8


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
