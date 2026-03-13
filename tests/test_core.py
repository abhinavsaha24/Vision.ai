"""
Tests for exchange adapter, order manager, and live safety.

These tests validate the core execution pipeline:
  - PaperAdapter: simulated fills with slippage and commission
  - OrderManager: order lifecycle and state tracking
  - LiveTradingSafety: pre-flight checks for live trading
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch
from backend.src.exchange.exchange_adapter import PaperAdapter, Order, Balance


# ==================================================
# PaperAdapter Tests
# ==================================================

class TestPaperAdapter:

    def test_market_buy_fills_immediately(self):
        adapter = PaperAdapter(initial_cash=10000, max_slippage=0)
        order = adapter.place_market_order("BTC/USDT", "buy", 0.1, price=50000)

        assert order.status == "filled"
        assert order.filled_quantity == 0.1
        assert order.side == "buy"
        assert order.commission > 0

    def test_market_sell_fills_immediately(self):
        adapter = PaperAdapter(initial_cash=10000, max_slippage=0)
        # First buy
        adapter.place_market_order("BTC/USDT", "buy", 0.1, price=50000)
        # Then sell
        order = adapter.place_market_order("BTC/USDT", "sell", 0.1, price=51000)

        assert order.status == "filled"
        assert order.filled_quantity == 0.1

    def test_insufficient_funds_rejected(self):
        adapter = PaperAdapter(initial_cash=100, max_slippage=0)  # Only $100
        order = adapter.place_market_order("BTC/USDT", "buy", 1.0, price=50000)

        assert order.status == "rejected"
        assert "Insufficient funds" in order.error

    def test_insufficient_holdings_rejected(self):
        adapter = PaperAdapter(initial_cash=10000)
        order = adapter.place_market_order("BTC/USDT", "sell", 1.0, price=50000)

        assert order.status == "rejected"
        assert "Insufficient holdings" in order.error

    def test_balance_updates_after_buy(self):
        adapter = PaperAdapter(initial_cash=10000, max_slippage=0, commission_rate=0)
        adapter.place_market_order("BTC/USDT", "buy", 0.1, price=50000)

        balance = adapter.get_balance()
        assert balance.total["BTC/USDT"] == 0.1
        assert balance.total["USDT"] == 5000.0

    def test_limit_order_fills(self):
        adapter = PaperAdapter(initial_cash=10000)
        order = adapter.place_limit_order("BTC/USDT", "buy", 0.05, price=40000)

        assert order.status == "filled"
        assert order.order_type == "limit"

    def test_cancel_all(self):
        adapter = PaperAdapter(initial_cash=10000)
        # In paper mode, orders fill immediately, so cancel_all returns 0
        count = adapter.cancel_all_orders()
        assert count == 0

    def test_order_is_terminal(self):
        order = Order(
            order_id="test", symbol="BTC/USDT", side="buy",
            order_type="market", quantity=0.1, price=50000,
            status="filled",
        )
        assert order.is_terminal() is True

        order.status = "pending"
        assert order.is_terminal() is False


# ==================================================
# OrderManager Tests
# ==================================================

class TestOrderManager:

    def test_submit_and_track(self):
        from backend.src.execution.order_manager import OrderManager
        adapter = PaperAdapter(initial_cash=10000, max_slippage=0)
        mgr = OrderManager(adapter)

        order = mgr.submit_market_order("BTC/USDT", "buy", 0.1, price=50000)

        assert order.status == "filled"
        assert mgr.total_filled == 1
        assert mgr.total_submitted == 1

    def test_rejected_order_tracked(self):
        from backend.src.execution.order_manager import OrderManager
        adapter = PaperAdapter(initial_cash=100)  # Tiny balance
        mgr = OrderManager(adapter)

        order = mgr.submit_market_order("BTC/USDT", "buy", 1.0, price=50000)

        assert order.status == "rejected"
        assert mgr.total_rejected == 1

    def test_order_history(self):
        from backend.src.execution.order_manager import OrderManager
        adapter = PaperAdapter(initial_cash=100000, max_slippage=0)
        mgr = OrderManager(adapter)

        mgr.submit_market_order("BTC/USDT", "buy", 0.1, price=50000)
        mgr.submit_market_order("ETH/USDT", "buy", 1.0, price=3000)

        history = mgr.get_recent_history()
        assert len(history) == 2

    def test_statistics(self):
        from backend.src.execution.order_manager import OrderManager
        adapter = PaperAdapter(initial_cash=100000, max_slippage=0)
        mgr = OrderManager(adapter)

        mgr.submit_market_order("BTC/USDT", "buy", 0.1, price=50000)
        stats = mgr.get_statistics()

        assert stats["total_submitted"] == 1
        assert stats["total_filled"] == 1
        assert stats["fill_rate"] == 1.0

    def test_cancel_all(self):
        from backend.src.execution.order_manager import OrderManager
        adapter = PaperAdapter(initial_cash=100000)
        mgr = OrderManager(adapter)

        count = mgr.cancel_all()
        assert count == 0  # No active orders in paper mode


# ==================================================
# LiveTradingSafety Tests
# ==================================================

class TestLiveTradingSafety:

    def _make_settings(self, **overrides):
        defaults = {
            "trading_mode": "paper",
            "live_trading_enabled": False,
            "binance_api_key": None,
            "binance_secret": None,
            "live_max_position_usd": 100.0,
        }
        defaults.update(overrides)
        return MagicMock(**defaults)

    def _make_risk_manager(self, kill_switch=False):
        rm = MagicMock()
        rm.kill_switch_active = kill_switch
        rm.limits = MagicMock()
        rm.limits.max_daily_loss = 0.05
        rm.limits.max_drawdown = 0.20
        return rm

    def test_default_settings_block_live(self):
        from backend.src.execution.live_safety import LiveTradingSafety
        safety = LiveTradingSafety(
            settings=self._make_settings(),
            risk_manager=self._make_risk_manager(),
        )
        assert safety.is_live_allowed() is False

    def test_enabled_but_no_keys_blocks(self):
        from backend.src.execution.live_safety import LiveTradingSafety
        safety = LiveTradingSafety(
            settings=self._make_settings(
                trading_mode="live",
                live_trading_enabled=True,
            ),
            risk_manager=self._make_risk_manager(),
        )
        assert safety.is_live_allowed() is False

    def test_kill_switch_blocks(self):
        from backend.src.execution.live_safety import LiveTradingSafety
        safety = LiveTradingSafety(
            settings=self._make_settings(
                trading_mode="live",
                live_trading_enabled=True,
                binance_api_key="real_key",
                binance_secret="real_secret",
            ),
            risk_manager=self._make_risk_manager(kill_switch=True),
        )
        assert safety.is_live_allowed() is False

    def test_report_dict_format(self):
        from backend.src.execution.live_safety import LiveTradingSafety
        safety = LiveTradingSafety(
            settings=self._make_settings(),
            risk_manager=self._make_risk_manager(),
        )
        report = safety.get_report_dict()

        assert "all_passed" in report
        assert "checks" in report
        assert isinstance(report["checks"], list)
        assert len(report["checks"]) >= 5  # At least 5 safety checks


# ==================================================
# ModelRegistry Tests
# ==================================================

class TestModelRegistry:

    def test_register_model(self, tmp_path):
        from backend.src.models.model_registry import ModelRegistry
        registry = ModelRegistry(model_dir=str(tmp_path), max_versions=5)

        version = registry.register_model(
            model_name="test_model",
            metrics={"accuracy": 0.75, "cv_accuracy_mean": 0.72},
            feature_names=["f1", "f2", "f3"],
        )

        assert version.accuracy == 0.75
        assert registry.active_version == version.version_id
        assert len(registry.versions) == 1

    def test_should_rollback_on_regression(self, tmp_path):
        from backend.src.models.model_registry import ModelRegistry
        registry = ModelRegistry(model_dir=str(tmp_path))

        registry.register_model("m1", {"accuracy": 0.80})

        # New model with lower accuracy
        should_roll = registry.should_rollback({"accuracy": 0.70})
        assert should_roll is True

    def test_should_not_rollback_on_improvement(self, tmp_path):
        from backend.src.models.model_registry import ModelRegistry
        registry = ModelRegistry(model_dir=str(tmp_path))

        registry.register_model("m1", {"accuracy": 0.70})

        should_roll = registry.should_rollback({"accuracy": 0.80})
        assert should_roll is False

    def test_registry_persists(self, tmp_path):
        from backend.src.models.model_registry import ModelRegistry

        # Save
        r1 = ModelRegistry(model_dir=str(tmp_path))
        r1.register_model("m1", {"accuracy": 0.75})

        # Reload
        r2 = ModelRegistry(model_dir=str(tmp_path))
        assert len(r2.versions) == 1
        assert r2.versions[0].accuracy == 0.75


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
