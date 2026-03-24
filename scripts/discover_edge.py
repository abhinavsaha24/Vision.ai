from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.src.platform.edge_schema import EdgeSchemaValidator
from backend.src.research.edge_discovery import DiscoveryConfig, EdgeDiscoveryEngine


def _normalize_symbol(symbol: str) -> str:
    s = str(symbol).upper().replace("/", "").replace("-", "")
    if s.endswith("USD") and not s.endswith("USDT"):
        s = s[:-3] + "USDT"
    return s


def _read_parquet_with_ts(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    if df.empty:
        return pd.DataFrame()
    cols_lower = {str(c).lower(): c for c in df.columns}
    ts_col = None
    for candidate in ("ts", "timestamp", "datetime", "date"):
        if candidate in cols_lower:
            ts_col = cols_lower[candidate]
            break
    if ts_col is not None:
        df["ts"] = pd.to_datetime(df[ts_col], utc=True)
        df = df.set_index("ts")
    else:
        df.index = pd.to_datetime(df.index, utc=True)
    return df.sort_index()


def _build_symbol_frames(symbols: list[str], research_dir: Path, flow_dir: Path, interval: str) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    frames: dict[str, pd.DataFrame] = {}
    rejected: list[dict[str, Any]] = []
    for symbol in symbols:
        normalized = _normalize_symbol(symbol)
        research_path = research_dir / f"{normalized}_{interval}.parquet"
        flow_path = flow_dir / f"{normalized}_{interval}.parquet"

        research_df = _read_parquet_with_ts(research_path)
        if research_df.empty:
            rejected.append({"symbol": symbol, "reason": ["missing_persisted_research_data"], "path": str(research_path)})
            continue

        required = ["open", "high", "low", "close", "volume"]
        missing = [col for col in required if col not in research_df.columns]
        if missing:
            rejected.append({"symbol": symbol, "reason": ["invalid_research_schema", *[f"missing:{m}" for m in missing]], "path": str(research_path)})
            continue

        frame = research_df.copy()
        flow_df = _read_parquet_with_ts(flow_path)
        if not flow_df.empty:
            add_cols = [c for c in flow_df.columns if c not in frame.columns]
            if add_cols:
                frame = frame.join(flow_df[add_cols], how="left")
        frame = frame.sort_index().ffill().dropna(subset=required)
        if frame.empty:
            rejected.append({"symbol": symbol, "reason": ["insufficient_persisted_rows"]})
            continue
        frames[symbol] = frame
    return frames, rejected


def _family(edge: dict[str, Any]) -> str:
    event = str(edge.get("event", ""))
    return event.split("_", 1)[0] if event else "unknown"


def _allocation_recommendation(top_edges: list[dict[str, Any]]) -> dict[str, Any]:
    if not top_edges:
        return {"status": "NO_TRADE", "weights": {}, "caps": {"per_symbol": 0.30, "per_family": 0.40}}

    weighted_rows = []
    for edge in top_edges:
        score = max(0.0, float(edge.get("oos_stats", {}).get("t_stat", 0.0) or 0.0)) * max(
            0.0, float(edge.get("oos_stats", {}).get("expectancy", 0.0) or 0.0)
        )
        if score <= 0.0:
            continue
        weighted_rows.append({
            "edge_id": edge.get("edge_id"),
            "assets": [str(a) for a in edge.get("assets", [])],
            "family": _family(edge),
            "score": score,
        })

    if not weighted_rows:
        return {"status": "NO_TRADE", "weights": {}, "caps": {"per_symbol": 0.30, "per_family": 0.40}}

    total = sum(float(r["score"]) for r in weighted_rows)
    symbol_weights: dict[str, float] = {}
    family_weights: dict[str, float] = {}
    for row in weighted_rows:
        w = float(row["score"]) / max(total, 1e-9)
        fam = str(row["family"])
        assets = row["assets"] or ["UNKNOWN"]
        family_weights[fam] = family_weights.get(fam, 0.0) + w
        for asset in assets:
            symbol_weights[asset] = symbol_weights.get(asset, 0.0) + (w / len(assets))

    per_symbol_cap = 0.30
    per_family_cap = 0.40
    symbol_weights = {k: min(per_symbol_cap, v) for k, v in symbol_weights.items()}
    family_weights = {k: min(per_family_cap, v) for k, v in family_weights.items()}

    norm = sum(symbol_weights.values()) or 1.0
    symbol_weights = {k: v / norm for k, v in symbol_weights.items()}
    return {
        "status": "ok",
        "weights": symbol_weights,
        "family_weights": family_weights,
        "caps": {"per_symbol": per_symbol_cap, "per_family": per_family_cap},
    }


def _validation_reports(
    symbol_frames: dict[str, pd.DataFrame],
    symbols_to_validate: list[str],
    validation_bars: int,
    top_edges: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    regime_breakdown: dict[str, Any] = {}
    edge_contribution_report: dict[str, Any] = {}

    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for edge in top_edges:
        for asset in edge.get("assets", []):
            by_symbol.setdefault(asset, []).append(edge)

    for symbol in symbols_to_validate:
        df = symbol_frames.get(symbol)
        if df is None:
            continue
        df_eval = df.tail(max(220, int(validation_bars)))
        if df_eval.empty or len(df_eval) < 220:
            regime_breakdown[symbol] = {"status": "insufficient_validation_data", "rows": int(len(df_eval))}
            edge_contribution_report[symbol] = {"status": "insufficient_validation_data", "rows": int(len(df_eval))}
            continue

        symbol_edges = by_symbol.get(symbol, [])
        if not symbol_edges:
            regime_breakdown[symbol] = {"status": "no_symbol_edges"}
            edge_contribution_report[symbol] = {"status": "no_symbol_edges"}
            continue

        regime_stats: dict[str, dict[str, float]] = {}
        for row in symbol_edges:
            conditions = row.get("conditions", {}) or {}
            stats = row.get("stats", {}) or {}
            regime = str(conditions.get("regime", "unknown"))
            bucket = regime_stats.setdefault(regime, {"count": 0.0, "expectancy_sum": 0.0, "samples_sum": 0.0})
            bucket["count"] += 1.0
            try:
                bucket["expectancy_sum"] += float(stats.get("expectancy", 0.0) or 0.0)
            except (TypeError, ValueError):
                bucket["expectancy_sum"] += 0.0
            try:
                bucket["samples_sum"] += float(stats.get("samples", 0.0) or 0.0)
            except (TypeError, ValueError):
                bucket["samples_sum"] += 0.0

        regime_breakdown[symbol] = {
            "rows": int(len(df_eval)),
            "regime_metrics": {
                k: {
                    "edges": int(v["count"]),
                    "mean_expectancy": float(v["expectancy_sum"] / max(v["count"], 1.0)),
                    "total_samples": float(v["samples_sum"]),
                }
                for k, v in regime_stats.items()
            },
        }

        top = sorted(
            [
                {
                    "edge_id": e.get("edge_id"),
                    "expectancy": float((e.get("stats", {}) or {}).get("expectancy", 0.0) or 0.0),
                    "samples": float((e.get("stats", {}) or {}).get("samples", 0.0) or 0.0),
                    "contribution_pnl_proxy": float((e.get("stats", {}) or {}).get("expectancy", 0.0) or 0.0)
                    * float((e.get("stats", {}) or {}).get("samples", 0.0) or 0.0),
                    "regime": str((e.get("conditions", {}) or {}).get("regime", "")),
                }
                for e in symbol_edges
            ],
            key=lambda x: float(x.get("contribution_pnl_proxy", 0.0)),
            reverse=True,
        )[:20]
        contribution_total = float(sum(float(x.get("contribution_pnl_proxy", 0.0)) for x in top))
        hhi = 0.0
        if contribution_total != 0.0 and top:
            shares = [abs(float(x.get("contribution_pnl_proxy", 0.0))) / max(abs(contribution_total), 1e-9) for x in top]
            hhi = float(sum(s * s for s in shares))
        edge_contribution_report[symbol] = {
            "total_contribution": contribution_total,
            "pnl_concentration_hhi": hhi,
            "top_edges": top,
        }
    return regime_breakdown, edge_contribution_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Institutional edge discovery with conditional surfaces and diagnostics")
    parser.add_argument("--symbols", nargs="+", default=["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD"])
    parser.add_argument("--period", default="730d")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--output-dir", default="data")
    parser.add_argument("--research-dir", default="data/research")
    parser.add_argument("--flow-dir", default="data/flow")
    parser.add_argument("--min-event-samples", type=int, default=200)
    parser.add_argument("--min-segment-samples", type=int, default=200)
    parser.add_argument("--min-assets", type=int, default=2)
    parser.add_argument("--validation-bars", type=int, default=600)
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    symbol_frames, pre_rejected = _build_symbol_frames(
        args.symbols,
        research_dir=Path(args.research_dir),
        flow_dir=Path(args.flow_dir),
        interval=args.interval,
    )

    discovery = EdgeDiscoveryEngine(
        DiscoveryConfig(
            min_event_samples=max(50, int(args.min_event_samples)),
            min_segment_samples=max(50, int(args.min_segment_samples)),
            min_assets_required=max(1, int(args.min_assets)),
        )
    )
    result = discovery.discover(symbol_frames)

    valid_edges, schema_rejected = EdgeSchemaValidator.filter_edges(result["edge_registry"].get("edges", []))
    result["edge_registry"]["edges"] = valid_edges
    schema_rejected_rows = [
        {"symbol": "registry", "edge_id": row.get("edge_id", "unknown"), "reason": row.get("reason", [])}
        for row in schema_rejected
    ]

    registry = result["edge_registry"]
    registry["assets"] = list(symbol_frames.keys())
    registry["interval"] = args.interval
    registry["generated_at"] = datetime.now(timezone.utc).isoformat()
    top_edges = [e for e in result["top_edges"] if e.get("edge_id") in {x.get("edge_id") for x in valid_edges}]
    rejected_all = [*pre_rejected, *result["rejected_edges"], *schema_rejected_rows]

    validate_symbols = sorted({asset for edge in top_edges for asset in edge.get("assets", [])})
    if not validate_symbols and symbol_frames:
        validate_symbols = [next(iter(symbol_frames.keys()))]

    regime_breakdown, edge_contribution_report = _validation_reports(
        symbol_frames,
        symbols_to_validate=validate_symbols,
        validation_bars=int(args.validation_bars),
        top_edges=top_edges,
    )

    diagnostics = result["diagnostics"]
    if len(top_edges) == 0:
        diagnostics["failure_summary"] = "no_valid_edges_after_statistical_and_oos_filters"
    else:
        diagnostics["failure_summary"] = "edges_discovered"

    registry_path = out_dir / "edge_registry.json"
    rejected_path = out_dir / "rejected_edges.json"
    top_path = out_dir / "top_edges.csv"
    regime_path = out_dir / "regime_performance_breakdown.json"
    contribution_path = out_dir / "edge_contribution_report.json"
    diagnostics_path = out_dir / "discovery_diagnostics.json"
    promotion_path = out_dir / "promotion_readiness.json"
    top5_path = out_dir / "top_5_edges.json"
    allocation_path = out_dir / "portfolio_allocation_recommendation.json"

    registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    rejected_path.write_text(json.dumps(rejected_all, indent=2), encoding="utf-8")
    regime_path.write_text(json.dumps(regime_breakdown, indent=2), encoding="utf-8")
    contribution_path.write_text(json.dumps(edge_contribution_report, indent=2), encoding="utf-8")
    diagnostics_path.write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
    top5 = top_edges[:5]
    top5_path.write_text(json.dumps(top5, indent=2), encoding="utf-8")
    allocation = _allocation_recommendation(top5)
    allocation_path.write_text(json.dumps(allocation, indent=2), encoding="utf-8")

    readiness = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "criteria": {
            "profit_factor_gt": 1.3,
            "sharpe_gt": 1.5,
            "max_drawdown_lt": 0.10,
            "trade_count_gt": 100,
            "oos_consistency_required": True,
            "live_pf_gt": 1.1,
            "live_days_required": 14,
        },
        "eligible_edge_ids": [
            e["edge_id"]
            for e in top_edges
            if float(e.get("stats", {}).get("profit_factor", 0.0)) > 1.3
            and float(e.get("stats", {}).get("sharpe", 0.0)) > 1.5
            and float(e.get("stats", {}).get("samples", 0.0)) > 100
            and float(e.get("oos_stats", {}).get("expectancy", 0.0)) > 0.0
        ],
        "status": "do_not_trade_until_live_shadow_passes",
    }
    promotion_path.write_text(json.dumps(readiness, indent=2), encoding="utf-8")

    top_rows = []
    top_columns = [
        "rank",
        "edge_id",
        "symbol",
        "event",
        "regime",
        "volatility_state",
        "session",
        "direction",
        "trades",
        "expectancy",
        "win_rate",
        "profit_factor",
        "t_stat",
        "oos_expectancy",
        "oos_profit_factor",
        "oos_t_stat",
        "assets",
        "confidence_score",
        "expected_return",
        "holding_period",
        "sample_size",
    ]
    for rank, edge in enumerate(top_edges[:100], start=1):
        conditions = edge.get("conditions", {}) or {}
        stats = edge.get("stats", {}) or {}
        oos_stats = edge.get("oos_stats", {}) or {}
        top_rows.append(
            {
                "rank": rank,
                "edge_id": edge.get("edge_id"),
                "symbol": "|".join(edge.get("assets", [])),
                "event": edge.get("event"),
                "regime": conditions.get("regime", None),
                "volatility_state": conditions.get("volatility_state", None),
                "session": conditions.get("session", None),
                "direction": edge.get("direction"),
                "trades": stats.get("samples", 0.0),
                "expectancy": stats.get("expectancy", 0.0),
                "win_rate": stats.get("win_rate", 0.0),
                "profit_factor": stats.get("profit_factor", 0.0),
                "t_stat": stats.get("t_stat", 0.0),
                "oos_expectancy": oos_stats.get("expectancy", 0.0),
                "oos_profit_factor": oos_stats.get("profit_factor", 0.0),
                "oos_t_stat": oos_stats.get("t_stat", 0.0),
                "assets": "|".join(edge.get("assets", [])),
                "confidence_score": edge.get("confidence_score", 0.0),
                "expected_return": edge.get("expected_return", stats.get("expectancy", 0.0)),
                "holding_period": edge.get("holding_period", edge.get("horizon", 4)),
                "sample_size": edge.get("sample_size", stats.get("samples", 0.0)),
            }
        )
    pd.DataFrame(top_rows, columns=top_columns).to_csv(top_path, index=False)

    print(f"edge_registry={registry_path}")
    print(f"rejected_edges={rejected_path}")
    print(f"top_edges={top_path}")
    print(f"regime_performance_breakdown={regime_path}")
    print(f"edge_contribution_report={contribution_path}")
    print(f"discovery_diagnostics={diagnostics_path}")
    print(f"promotion_readiness={promotion_path}")
    print(f"top_5_edges={top5_path}")
    print(f"portfolio_allocation_recommendation={allocation_path}")
    print(f"accepted_edges={len(top_edges)} rejected_edges={len(rejected_all)}")
    if len(top_edges) == 0:
        print("NO TRADE")


if __name__ == "__main__":
    main()
