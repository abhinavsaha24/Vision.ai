from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.src.platform.alpha_engine import AlphaEngine
from backend.src.platform.market_context import MarketContextFetcher
from backend.src.research.alpha_validation import AlphaValidationEngine


def fetch_data(symbol: str, period: str, interval: str) -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval=interval, auto_adjust=False)
    if df is None or df.empty:
        raise RuntimeError("No data downloaded")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]).lower().replace(" ", "_") for c in df.columns]
    else:
        df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]
    base = df[["open", "high", "low", "close", "volume"]].dropna().sort_index()
    return MarketContextFetcher().enrich_ohlcv(base, symbol=symbol, interval=interval)


def make_engine_factory(params: dict[str, float | int]):
    def _factory() -> AlphaEngine:
        return AlphaEngine(
            edge_min_win_rate=float(params["edge_min_win_rate"]),
            edge_min_profit_factor=float(params["edge_min_profit_factor"]),
            edge_min_t_stat=float(params["edge_min_t_stat"]),
            edge_min_expectancy=float(params["edge_min_expectancy"]),
            fallback_top_k=int(params["fallback_top_k"]),
            trend_entry_threshold=float(params["trend_entry_threshold"]),
            range_entry_threshold=float(params["range_entry_threshold"]),
            min_confidence=float(params["min_confidence"]),
            max_trades_24h=int(params["max_trades_24h"]),
            min_hours_between_trades=int(params["min_hours_between_trades"]),
            weak_tier_max_cap=float(params["weak_tier_max_cap"]),
        )

    return _factory


def _regime_stability_pass(
    regime_report: dict[str, Any],
    min_regime_coverage: float,
    min_regime_trades: int,
) -> tuple[bool, dict[str, Any]]:
    tracked = ["trend", "range", "high_volatility"]
    sufficient = []
    unstable = []
    filtered_out = []
    for label in tracked:
        section = regime_report.get(label, {})
        if not section.get("sufficient", False):
            filtered_out.append({"label": label, "reason": "insufficient_segment_data"})
            continue
        metrics = section.get("metrics", {})
        coverage_ratio = float(section.get("coverage_ratio", 0.0) or 0.0)
        trades = int(metrics.get("trades", 0) or 0)
        if coverage_ratio < min_regime_coverage:
            filtered_out.append(
                {
                    "label": label,
                    "reason": "low_coverage",
                    "coverage_ratio": coverage_ratio,
                }
            )
            continue
        if trades < min_regime_trades:
            filtered_out.append(
                {
                    "label": label,
                    "reason": "low_trades",
                    "trades": trades,
                }
            )
            continue
        sufficient.append(label)
        pf = float(metrics.get("profit_factor", 0.0) or 0.0)
        sharpe = float(metrics.get("sharpe", 0.0) or 0.0)
        dd = float(metrics.get("max_drawdown", 1.0) or 1.0)
        expectancy = float(metrics.get("expectancy", 0.0) or 0.0)
        if pf < 1.0 or sharpe < 0.0 or dd > 0.12 or expectancy <= 0.0:
            unstable.append(label)

    passed = len(sufficient) >= 2 and not unstable
    return (
        passed,
        {
            "sufficient_segments": sufficient,
            "unstable_segments": unstable,
            "filtered_out_segments": filtered_out,
            "required_min": 2,
            "min_regime_coverage": min_regime_coverage,
            "min_regime_trades": min_regime_trades,
        },
    )


def staged_objective(
    candidate: dict[str, Any],
    min_medium_trades: int,
    min_medium_pf: float,
    min_medium_sharpe: float,
    min_short_pf: float,
    min_short_sharpe: float,
    min_short_trades: int,
) -> float:
    short_bt = candidate["short"]["backtest"]
    medium_bt = candidate["medium"]["backtest"]

    short_dd = float(short_bt["max_drawdown"])
    short_pf = float(short_bt["profit_factor"])
    short_sharpe = float(short_bt["sharpe"])
    medium_dd = float(medium_bt["max_drawdown"])
    medium_pf = float(medium_bt["profit_factor"])
    medium_sharpe = float(medium_bt["sharpe"])
    dd_excess = max(0.0, short_dd - 0.10) + max(0.0, medium_dd - 0.10)

    short_trades = float(short_bt["trades"])
    medium_trades = float(medium_bt["trades"])
    trade_deficit = max(0.0, float(min_short_trades) - short_trades) + max(0.0, float(min_medium_trades) - medium_trades)
    short_trade_fail = short_trades < float(min_short_trades)
    short_pf_fail = short_pf < float(min_short_pf)
    short_sharpe_fail = short_sharpe < float(min_short_sharpe)
    medium_trade_fail = medium_trades < float(min_medium_trades)
    medium_pf_fail = medium_pf < float(min_medium_pf)
    medium_sharpe_fail = medium_sharpe < float(min_medium_sharpe)
    regime_fail = not bool(candidate.get("regime_stability", {}).get("pass", False))

    if (
        dd_excess > 0
        or short_trade_fail
        or short_pf_fail
        or short_sharpe_fail
        or medium_trade_fail
        or medium_pf_fail
        or regime_fail
        or medium_sharpe_fail
    ):
        return (
            -100.0
            - (dd_excess * 300.0)
            - (trade_deficit * 0.5)
            - (20.0 if short_trade_fail else 0.0)
            - (20.0 if short_pf_fail else 0.0)
            - (10.0 if short_sharpe_fail else 0.0)
            - (35.0 if medium_trade_fail else 0.0)
            - (25.0 if medium_pf_fail else 0.0)
            - (12.0 if medium_sharpe_fail else 0.0)
            - (20.0 if regime_fail else 0.0)
        )


    pf_avg = (float(short_bt["profit_factor"]) + float(medium_bt["profit_factor"])) / 2.0
    sharpe_avg = (float(short_bt["sharpe"]) + float(medium_bt["sharpe"])) / 2.0

    wf_short = candidate["short"].get("walk_forward", {})
    wf_medium = candidate["medium"].get("walk_forward", {})
    wf_pf = (
        float(wf_short.get("profit_factor_mean", 0.0) or 0.0)
        + float(wf_medium.get("profit_factor_mean", 0.0) or 0.0)
    ) / 2.0
    wf_sharpe = (
        float(wf_short.get("sharpe_mean", 0.0) or 0.0)
        + float(wf_medium.get("sharpe_mean", 0.0) or 0.0)
    ) / 2.0

    regime_bonus = 1.0 if candidate["regime_stability"]["pass"] else -1.0
    pass_bonus = 1.5 if candidate["pass_targets_short"] and candidate["pass_targets_medium"] else 0.0

    return (
        (pf_avg * 2.4)
        + (sharpe_avg * 0.9)
        + (wf_pf * 0.45)
        + (wf_sharpe * 0.2)
        + regime_bonus
        + pass_bonus
        - (trade_deficit * 0.25)
    )


def prefilter_score(short_bt: dict[str, Any], medium_bt: dict[str, Any]) -> float:
    short_dd = float(short_bt["max_drawdown"])
    medium_dd = float(medium_bt["max_drawdown"])
    dd_excess = max(0.0, short_dd - 0.10) + max(0.0, medium_dd - 0.10)

    short_trades = float(short_bt["trades"])
    medium_trades = float(medium_bt["trades"])
    trade_deficit = max(0.0, 25.0 - short_trades) + max(0.0, 25.0 - medium_trades)

    pf_avg = (float(short_bt["profit_factor"]) + float(medium_bt["profit_factor"])) / 2.0
    sharpe_avg = (float(short_bt["sharpe"]) + float(medium_bt["sharpe"])) / 2.0
    return (pf_avg * 2.2) + (sharpe_avg * 0.9) - (dd_excess * 120.0) - (trade_deficit * 0.4)


def passes_targets_dict(metrics: dict[str, Any]) -> bool:
    return (
        float(metrics["profit_factor"]) > 1.5
        and float(metrics["sharpe"]) > 1.5
        and float(metrics["max_drawdown"]) < 0.10
        and int(metrics["trades"]) >= 25
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTC-USD")
    parser.add_argument("--period", default="90d")
    parser.add_argument("--medium-period", default="365d")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--output", default="alpha_tuning_result.json")
    parser.add_argument("--max-combos", type=int, default=40)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--shortlist-size", type=int, default=8)
    parser.add_argument("--wf-windows", type=int, default=5)
    parser.add_argument("--medium-eval-bars", type=int, default=1400)
    parser.add_argument("--medium-wf", action="store_true")
    parser.add_argument("--min-regime-coverage", type=float, default=0.08)
    parser.add_argument("--min-regime-trades", type=int, default=15)
    parser.add_argument("--min-medium-trades", type=int, default=25)
    parser.add_argument("--min-medium-pf", type=float, default=1.2)
    parser.add_argument("--min-medium-sharpe", type=float, default=0.5)
    parser.add_argument("--min-short-trades", type=int, default=20)
    parser.add_argument("--min-short-pf", type=float, default=1.2)
    parser.add_argument("--min-short-sharpe", type=float, default=0.5)
    args = parser.parse_args()

    df_short = fetch_data(args.symbol, args.period, args.interval)
    df_medium = fetch_data(args.symbol, args.medium_period, args.interval)
    medium_eval_bars = max(400, int(args.medium_eval_bars))
    df_medium_eval = df_medium.tail(medium_eval_bars)

    grid = {
        "edge_min_win_rate": [0.50, 0.52, 0.54],
        "edge_min_profit_factor": [1.05, 1.10, 1.15],
        "edge_min_t_stat": [1.4, 1.6, 1.8],
        "edge_min_expectancy": [0.0],
        "fallback_top_k": [1, 2],
        "trend_entry_threshold": [0.16, 0.18, 0.20],
        "range_entry_threshold": [0.13, 0.15, 0.17],
        "min_confidence": [0.50, 0.52, 0.55],
        "max_trades_24h": [4, 5, 6],
        "min_hours_between_trades": [1],
        "weak_tier_max_cap": [0.03, 0.04, 0.05],
    }

    keys = list(grid.keys())
    combos = list(itertools.product(*[grid[k] for k in keys]))
    if args.max_combos > 0:
        combos = combos[: args.max_combos]

    prefiltered: list[dict[str, Any]] = []
    for combo in combos:
        params = {k: combo[i] for i, k in enumerate(keys)}
        engine = AlphaValidationEngine(
            fee_bps=6.0,
            slippage_bps=5.0,
            alpha_engine_factory=make_engine_factory(params),
        )

        bt_short, _ = engine.run_backtest(df_short)
        bt_medium, _ = engine.run_backtest(df_medium_eval)

        prefiltered.append(
            {
                "params": params,
                "short_backtest": bt_short.__dict__,
                "medium_backtest": bt_medium.__dict__,
                "prefilter_score": prefilter_score(bt_short.__dict__, bt_medium.__dict__),
            }
        )

    prefiltered = sorted(
        prefiltered,
        key=lambda x: float(x["prefilter_score"]),
        reverse=True,
    )
    shortlist_size = max(1, int(args.shortlist_size))
    shortlist = prefiltered[:shortlist_size]

    ranked: list[dict[str, Any]] = []
    for item in shortlist:
        params = item["params"]
        engine = AlphaValidationEngine(
            fee_bps=6.0,
            slippage_bps=5.0,
            alpha_engine_factory=make_engine_factory(params),
        )
        bt_short = item["short_backtest"]
        bt_medium = item["medium_backtest"]
        wf_short = engine.walk_forward(df_short, windows=max(3, int(args.wf_windows)))
        wf_medium = (
            engine.walk_forward(df_medium_eval, windows=max(3, int(args.wf_windows)))
            if args.medium_wf
            else {"skipped": True}
        )
        regime_medium = engine.regime_segmented_backtest(df_medium_eval)
        regime_pass, regime_detail = _regime_stability_pass(
            regime_medium,
            min_regime_coverage=float(args.min_regime_coverage),
            min_regime_trades=int(args.min_regime_trades),
        )

        candidate = {
            "params": params,
            "short": {
                "period": args.period,
                "backtest": bt_short,
                "walk_forward": wf_short,
            },
            "medium": {
                "period": args.medium_period,
                "backtest": bt_medium,
                "walk_forward": wf_medium,
            },
            "regime_stability": {
                "pass": regime_pass,
                "detail": regime_detail,
                "report": regime_medium,
            },
            "pass_targets_short": passes_targets_dict(bt_short),
            "pass_targets_medium": passes_targets_dict(bt_medium),
            "prefilter_score": float(item["prefilter_score"]),
            "min_medium_trades": int(args.min_medium_trades),
            "min_medium_pf": float(args.min_medium_pf),
            "min_medium_sharpe": float(args.min_medium_sharpe),
            "min_short_trades": int(args.min_short_trades),
            "min_short_pf": float(args.min_short_pf),
            "min_short_sharpe": float(args.min_short_sharpe),
        }
        candidate["score"] = staged_objective(
            candidate,
            min_medium_trades=int(args.min_medium_trades),
            min_medium_pf=float(args.min_medium_pf),
            min_medium_sharpe=float(args.min_medium_sharpe),
            min_short_trades=int(args.min_short_trades),
            min_short_pf=float(args.min_short_pf),
            min_short_sharpe=float(args.min_short_sharpe),
        )
        candidate["promotable"] = bool(candidate["score"] > 0)
        ranked.append(candidate)

    ranked = sorted(ranked, key=lambda x: float(x["score"]), reverse=True)
    top_n = max(1, int(args.top_n))
    top_candidates = ranked[:top_n]
    best = top_candidates[0] if top_candidates else None

    result = {
        "symbol": args.symbol,
        "interval": args.interval,
        "short_period": args.period,
        "medium_period": args.medium_period,
        "max_combos": args.max_combos,
        "shortlist_size": shortlist_size,
        "evaluated": len(combos),
        "prefiltered": len(shortlist),
        "promotable_count": len([c for c in ranked if bool(c.get("promotable", False))]),
        "best": best,
        "top_candidates": top_candidates,
    }

    print("=== Best Candidate ===")
    print(best)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"saved_result={args.output}")


if __name__ == "__main__":
    main()
