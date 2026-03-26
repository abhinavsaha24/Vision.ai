"""
Unit tests for monitoring, safety, and metrics collection modules.

Tests institutional-grade monitoring infrastructure:
  - ExecutionMonitor (execution quality assessment)
  - RiskMonitor (risk state assessment)
  - ExecutionMetricsCollector (metrics aggregation)
  - LiveGuard (policy enforcement)
  - SystemWatchdog (component health)
"""

import pytest
from datetime import datetime
from typing import Dict

from backend.src.monitoring.execution_monitor import ExecutionMonitor
from backend.src.monitoring.risk_monitor import RiskMonitor
from backend.src.monitoring.execution_metrics_collector import ExecutionMetricsCollector
from backend.src.monitoring.metrics_collector import MetricsCollector
from backend.src.safety.live_guard import LiveGuard
from backend.src.safety.system_watchdog import SystemWatchdog


class TestExecutionMonitor:
    """Test ExecutionMonitor quality assessment."""
    
    def test_good_execution_quality(self):
        """Test excellent execution metrics."""
        monitor = ExecutionMonitor()
        result = monitor.assess({
            "avg_latency_ms": 50.0,
            "avg_slippage_bps": 2.0,
        })
        
        assert result["quality"] == "good"
        assert result["avg_latency_ms"] == 50.0
        assert result["avg_slippage_bps"] == 2.0
        assert "latency_high" not in (result.get("alerts") or [])
    
    def test_degraded_execution_quality(self):
        """Test degraded execution metrics."""
        monitor = ExecutionMonitor()
        result = monitor.assess({
            "avg_latency_ms": 900.0,
            "avg_slippage_bps": 25.0,
        })
        
        assert result["quality"] == "degraded"
        assert "latency_high" in result["alerts"]
        assert "slippage_high" in result["alerts"]
    
    def test_critical_latency(self):
        """Test critical latency threshold."""
        monitor = ExecutionMonitor()
        result = monitor.assess({
            "avg_latency_ms": 2000.0,
            "avg_slippage_bps": 5.0,
        })
        
        assert result["quality"] == "critical"
    
    def test_critical_slippage(self):
        """Test critical slippage threshold."""
        monitor = ExecutionMonitor()
        result = monitor.assess({
            "avg_latency_ms": 100.0,
            "avg_slippage_bps": 50.0,
        })
        
        assert result["quality"] == "critical"


class TestRiskMonitor:
    """Test RiskMonitor risk state assessment."""
    
    def test_healthy_risk_state(self):
        """Test healthy risk state."""
        monitor = RiskMonitor()
        result = monitor.assess({
            "drawdown_pct": 0.05,
            "var_breach": False,
            "exposure_ok": True,
        })
        
        assert result["status"] == "healthy"
    
    def test_warning_risk_state(self):
        """Test warning risk state (drawdown exceeded)."""
        monitor = RiskMonitor()
        result = monitor.assess({
            "drawdown_pct": 0.10,
            "var_breach": False,
            "exposure_ok": True,
        })
        
        assert result["status"] == "warning"
    
    def test_critical_risk_state(self):
        """Test critical risk state (multiple issues)."""
        monitor = RiskMonitor()
        result = monitor.assess({
            "drawdown_pct": 0.15,
            "var_breach": True,
            "exposure_ok": False,
        })
        
        assert result["status"] == "critical"
    
    def test_risk_state_from_breach(self):
        """Test risk state with VaR breach but good exposure."""
        monitor = RiskMonitor()
        result = monitor.assess({
            "drawdown_pct": 0.02,
            "var_breach": True,
            "exposure_ok": True,
        })
        
        # var_breach alone triggers warning
        assert result["status"] == "warning"
    
    def test_critical_from_var_breach_and_exposure(self):
        """Test critical state from var_breach and bad exposure."""
        monitor = RiskMonitor()
        result = monitor.assess({
            "drawdown_pct": 0.05,
            "var_breach": True,
            "exposure_ok": False,
        })
        
        # var_breach AND bad exposure triggers critical
        assert result["status"] == "critical"


class TestExecutionMetricsCollector:
    """Test ExecutionMetricsCollector aggregation and assessment."""
    
    def test_no_data_state(self):
        """Test collector with no data."""
        collector = ExecutionMetricsCollector(window_size=10)
        metrics = collector.get_current_metrics()
        
        assert metrics["avg_latency_ms"] == 0.0
        assert metrics["avg_slippage_bps"] == 0.0
        assert metrics["status"] == "no_data"
    
    def test_record_order_result(self):
        """Test recording individual order results."""
        collector = ExecutionMetricsCollector(window_size=10)
        
        collector.record_order_result({
            "latency_ms": 100.0,
            "slippage_bps": 5.0,
            "status": "FILLED",
            "symbol": "BTC/USDT",
        })
        
        assert collector.total_orders == 1
        assert len(collector.metrics_history) == 1
    
    def test_quality_excellent(self):
        """Test quality assessment for excellent metrics."""
        collector = ExecutionMetricsCollector()
        quality = collector._assess_quality(latency_ms=50.0, slippage_bps=2.0)
        assert quality == "excellent"
    
    def test_quality_good(self):
        """Test quality assessment for good metrics."""
        collector = ExecutionMetricsCollector()
        quality = collector._assess_quality(latency_ms=300.0, slippage_bps=8.0)
        assert quality == "good"
    
    def test_quality_degraded(self):
        """Test quality assessment for degraded metrics."""
        collector = ExecutionMetricsCollector()
        quality = collector._assess_quality(latency_ms=1000.0, slippage_bps=20.0)
        assert quality == "degraded"
    
    def test_quality_critical(self):
        """Test quality assessment for critical metrics."""
        collector = ExecutionMetricsCollector()
        quality = collector._assess_quality(latency_ms=2000.0, slippage_bps=50.0)
        assert quality == "critical"
    
    def test_get_full_report(self):
        """Test comprehensive metrics report."""
        collector = ExecutionMetricsCollector(window_size=10)
        
        # Add multiple data points
        for i in range(5):
            collector.record_order_result({
                "latency_ms": float(100 * i),
                "slippage_bps": float(2 * i),
                "status": "FILLED",
                "symbol": "BTC/USDT",
            })
        
        report = collector.get_full_report()
        
        assert report["current"]["status"] == "active"
        assert report["rolling"]["window_size"] == 5
        assert report["total_orders_tracked"] == 5


class TestMetricsCollector:
    """Test MetricsCollector for timeseries snapshots."""
    
    def test_push_snapshot(self):
        """Test pushing a metric snapshot."""
        collector = MetricsCollector(maxlen=100)
        
        collector.push({
            "latency_ms": 150.0,
            "slippage_bps": 5.0,
            "equity": 100500.0,
        })
        
        assert len(collector.snapshots) == 1
    
    def test_latest_snapshot(self):
        """Test retrieving latest snapshot."""
        collector = MetricsCollector(maxlen=100)
        
        collector.push({"value": 1})
        collector.push({"value": 2})
        
        latest = collector.latest()
        assert latest["value"] == 2
    
    def test_summary(self):
        """Test metrics summary."""
        collector = MetricsCollector(maxlen=100)
        
        for i in range(5):
            collector.push({"value": i})
        
        summary = collector.summary()
        assert summary["count"] == 5
        assert summary["latest"]["value"] == 4
    
    def test_maxlen_enforcement(self):
        """Test that maxlen is respected."""
        collector = MetricsCollector(maxlen=5)
        
        for i in range(10):
            collector.push({"value": i})
        
        assert len(collector.snapshots) == 5


class TestLiveGuard:
    """Test LiveGuard policy enforcement."""
    
    def test_allow_live_when_all_ready(self):
        """Test allow_live when all components are ready."""
        guard = LiveGuard()
        
        readiness = {
            "all_ready": True,
            "overall_score": 95.0,
        }
        risk = {
            "status": "healthy",
        }
        execution = {
            "quality": "good",
        }
        
        result = guard.evaluate(readiness, risk, execution)
        assert result["allow_live"] is True
    
    def test_block_live_on_critical_risk(self):
        """Test blocking live when risk is critical."""
        guard = LiveGuard()
        
        readiness = {
            "all_ready": True,
            "overall_score": 95.0,
        }
        risk = {
            "status": "critical",
        }
        execution = {
            "quality": "good",
        }
        
        result = guard.evaluate(readiness, risk, execution)
        assert result["allow_live"] is False
        assert len(result.get("blocked_reasons", [])) > 0
    
    def test_block_live_on_critical_execution(self):
        """Test blocking live when execution quality is critical."""
        guard = LiveGuard()
        
        readiness = {
            "all_ready": True,
            "overall_score": 95.0,
        }
        risk = {
            "status": "healthy",
        }
        execution = {
            "quality": "critical",
        }
        
        result = guard.evaluate(readiness, risk, execution)
        assert result["allow_live"] is False
    
    def test_block_live_on_bad_readiness(self):
        """Test blocking live when readiness is poor."""
        guard = LiveGuard()
        
        readiness = {
            "all_ready": False,
            "overall_score": 60.0,
        }
        risk = {
            "status": "healthy",
        }
        execution = {
            "quality": "good",
        }
        
        result = guard.evaluate(readiness, risk, execution)
        assert result["allow_live"] is False


class TestSystemWatchdog:
    """Test SystemWatchdog component health monitoring."""
    
    def test_beat_recording(self):
        """Test recording component heartbeat."""
        watchdog = SystemWatchdog()
        
        watchdog.beat("execution_engine")
        watchdog.beat("data_fetcher")
        
        assert len(watchdog.heartbeats) == 2
    
    def test_healthy_status(self):
        """Test healthy watchdog status."""
        watchdog = SystemWatchdog()
        
        watchdog.beat("execution_engine")
        watchdog.beat("data_fetcher")
        
        status = watchdog.status(max_stale_seconds=10.0)
        assert status["healthy"] is True
        assert len(status["stale_components"]) == 0
    
    def test_stale_component_detection(self):
        """Test detection of stale components."""
        watchdog = SystemWatchdog()
        
        import time
        watchdog.beat("execution_engine")
        
        # Set component heartbeat to old timestamp
        old_time = time.time() - 30.0  # 30 seconds ago
        watchdog.heartbeats["execution_engine"] = old_time
        
        status = watchdog.status(max_stale_seconds=10.0)
        assert "execution_engine" in status["stale_components"]
        assert status["healthy"] is False


class TestIntegrationExecutionMetrics:
    """Integration tests for execution metrics flow."""
    
    def test_end_to_end_metrics_flow(self):
        """Test complete metrics collection flow."""
        collector = ExecutionMetricsCollector(window_size=50)
        monitor = ExecutionMonitor()
        
        # Simulate order executions
        for i in range(10):
            collector.record_order_result({
                "latency_ms": 100.0 + i * 10,
                "slippage_bps": 3.0 + i * 0.5,
                "status": "FILLED",
                "symbol": "BTC/USDT",
            })
        
        # Get metrics
        current = collector.get_current_metrics()
        
        # Assess with monitor
        assessment = monitor.assess(current)
        
        assert assessment["avg_latency_ms"] >= 0
        assert assessment["avg_slippage_bps"] >= 0
        assert assessment["quality"] in ["excellent", "good", "degraded", "critical"]
    
    def test_readiness_component_integration(self):
        """Test metrics flowing into readiness assessment."""
        exec_collector = ExecutionMetricsCollector()
        risk_monitor = RiskMonitor()
        exec_monitor = ExecutionMonitor()
        live_guard = LiveGuard()
        
        # Build readiness and risk states
        readiness = {
            "all_ready": True,
            "overall_score": 95.0,
        }
        
        risk_state = {
            "drawdown_pct": 0.05,
            "var_breach": False,
            "exposure_ok": True,
        }
        
        risk_health = risk_monitor.assess(risk_state)
        exec_quality = exec_monitor.assess({
            "avg_latency_ms": 150.0,
            "avg_slippage_bps": 5.0,
        })
        
        guard_eval = live_guard.evaluate(readiness, risk_health, exec_quality)
        
        assert guard_eval["allow_live"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
