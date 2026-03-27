from backend.src.platform.signal_orchestrator import SignalOrchestrator


def test_signal_orchestrator_produces_unified_score() -> None:
    orchestrator = SignalOrchestrator()
    tick = {
        "pe_ratio": 14.0,
        "revenue_growth_yoy": 0.12,
        "debt_to_equity": 0.4,
        "gross_margin": 0.52,
        "roic": 0.18,
        "real_rate": 0.01,
        "inflation_yoy": 0.025,
        "gdp_growth_yoy": 0.028,
        "credit_spread": 0.018,
        "sector_momentum": 0.05,
    }
    alpha = {
        "price": 100.0,
        "score": 0.62,
        "confidence": 0.74,
    }

    result = orchestrator.evaluate(tick, alpha)

    assert "unified_score" in result
    assert result["unified_score"] > 0.0
    assert "components" in result
    assert "equity_screening" in result["components"]
    assert "dcf" in result["components"]
    assert "macro_regime" in result["components"]


def test_signal_orchestrator_reacts_to_weak_quant_signal() -> None:
    orchestrator = SignalOrchestrator()
    tick = {}
    alpha_strong = {"price": 100.0, "score": 0.8, "confidence": 0.8}
    alpha_weak = {"price": 100.0, "score": 0.1, "confidence": 0.2}

    strong = orchestrator.evaluate(tick, alpha_strong)
    weak = orchestrator.evaluate(tick, alpha_weak)

    assert strong["unified_score"] > weak["unified_score"]
