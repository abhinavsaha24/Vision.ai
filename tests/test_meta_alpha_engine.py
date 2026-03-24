from backend.src.models.meta_alpha_engine import MetaAlphaEngine


def test_meta_alpha_generates_buy_signal_with_positive_inputs():
    engine = MetaAlphaEngine()

    result = engine.infer(
        prediction={"probability": 0.74},
        strategy_result={"score": 0.35},
        sentiment_score=0.25,
        regime={"trend": "uptrend", "volatility": "low_volatility"},
        market_snapshot={"order_book_imbalance": 0.18, "spread_bps": 3.2, "stale": False},
    )

    assert result["signal"] == "long"
    assert result["probability"] > 0.55
    assert result["confidence"] > 0


def test_meta_alpha_generates_sell_signal_with_negative_inputs():
    engine = MetaAlphaEngine()

    result = engine.infer(
        prediction={"probability": 0.22},
        strategy_result={"score": -0.40},
        sentiment_score=-0.30,
        regime={"trend": "sideways", "volatility": "high_volatility"},
        market_snapshot={"order_book_imbalance": -0.22, "spread_bps": 12.5, "stale": False},
    )

    assert result["signal"] == "short"
    assert result["probability"] < 0.45


def test_meta_alpha_includes_ranked_contributors():
    engine = MetaAlphaEngine()

    result = engine.infer(
        prediction={"probability": 0.50},
        strategy_result={"score": 0.0},
        sentiment_score=0.0,
        regime={},
        market_snapshot={"order_book_imbalance": 0.0, "spread_bps": 0.0, "stale": True},
    )

    assert result["contributing_signals"]
    assert all("name" in item and "contribution" in item for item in result["contributing_signals"])
    assert "weighted_scores" in result
    assert "thresholds" in result


def test_meta_alpha_raises_thresholds_in_high_volatility():
    engine = MetaAlphaEngine()

    calm = engine.infer(
        prediction={"probability": 0.58},
        strategy_result={"score": 0.2},
        sentiment_score=0.1,
        regime={"trend": "uptrend", "volatility": "low_volatility"},
        market_snapshot={"order_book_imbalance": 0.1, "spread_bps": 3.0, "stale": False},
    )
    stressed = engine.infer(
        prediction={"probability": 0.58},
        strategy_result={"score": 0.2},
        sentiment_score=0.1,
        regime={"trend": "uptrend", "volatility": "high_volatility"},
        market_snapshot={"order_book_imbalance": 0.1, "spread_bps": 20.0, "stale": True},
    )

    assert stressed["thresholds"]["entry"] >= calm["thresholds"]["entry"]
    assert stressed["confidence"] <= calm["confidence"]


def test_meta_alpha_cost_aware_edge_gating_reduces_conviction():
    engine = MetaAlphaEngine()

    strong_edge = engine.infer(
        prediction={"probability": 0.72},
        strategy_result={"score": 0.35},
        sentiment_score=0.15,
        regime={"market_state": "TREND", "volatility": "low_volatility"},
        market_snapshot={
            "order_book_imbalance": 0.16,
            "volume_delta": 0.22,
            "volatility_expansion": 0.18,
            "spread_bps": 2.5,
            "book_depth_usd": 800000,
            "stale": False,
        },
    )

    weak_edge = engine.infer(
        prediction={"probability": 0.72},
        strategy_result={"score": 0.35},
        sentiment_score=0.15,
        regime={"market_state": "TREND", "volatility": "low_volatility"},
        market_snapshot={
            "order_book_imbalance": 0.16,
            "volume_delta": 0.22,
            "volatility_expansion": 0.18,
            "spread_bps": 22.0,
            "book_depth_usd": 40000,
            "stale": True,
        },
    )

    assert strong_edge["market_context"]["expected_edge_bps"] > weak_edge["market_context"]["expected_edge_bps"]
    assert strong_edge["confidence"] > weak_edge["confidence"]
    assert weak_edge["thresholds"]["entry"] >= 0.0