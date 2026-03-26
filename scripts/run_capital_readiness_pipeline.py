from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import yfinance as yf

from backend.src.monitoring.failure_diagnostics import FailureDiagnostics
from backend.src.platform.registry_versioning import RegistryVersioning
from backend.src.research.alpha_validation import AlphaValidationEngine


def _run_discovery(
    period: str,
    interval: str,
    out_dir: str,
    min_event_samples: int | None = None,
    min_segment_samples: int | None = None,
    min_assets: int | None = None,
) -> None:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "discover_edge.py"),
        "--period",
        period,
        "--interval",
        interval,
        "--output-dir",
        out_dir,
    ]
    if min_event_samples is not None:
        cmd.extend(["--min-event-samples", str(int(min_event_samples))])
    if min_segment_samples is not None:
        cmd.extend(["--min-segment-samples", str(int(min_segment_samples))])
    if min_assets is not None:
        cmd.extend(["--min-assets", str(int(min_assets))])
    subprocess.run(cmd, check=True, timeout=60)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_shadow_artifact(out_dir: Path) -> dict[str, Any]:
    shadow = _load_json(out_dir / "shadow_performance.json")
    if shadow:
        return shadow
    runtime = _load_json(out_dir / "runtime_status.json")
    if isinstance(runtime, dict):
        payload = runtime.get("shadow_performance", {})
        if isinstance(payload, dict):
            return payload
    return {}


def _download_ohlcv(symbol: str, period: str, interval: str) -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval=interval, auto_adjust=False, progress=False)
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]).lower() for c in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]
    expected = ["open", "high", "low", "close", "volume"]
    missing = [col for col in expected if col not in df.columns]
    if missing:
        for col in missing:
            df[col] = pd.NA
    return df[expected].dropna().sort_index()


def _serialize_backtest(bt: Any) -> dict[str, Any]:
    if hasattr(bt, "to_dict"):
        try:
            payload = bt.to_dict()
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return {
        k: v
        for k, v in vars(bt).items()
        if isinstance(v, (str, int, float, bool, list, dict, type(None)))
    }


def _normalize_symbol(symbol: str) -> str:
    s = str(symbol).upper().replace("/", "").replace("-", "")
    if s.endswith("USD") and not s.endswith("USDT"):
        s = s[:-3] + "USDT"
    return s


def _parse_interval(interval: str) -> pd.Timedelta | None:
    token = str(interval).strip().lower()
    match = re.match(r"^(\d+)([mhdw])$", token)
    if not match:
        return None
    count = int(match.group(1))
    unit = match.group(2)
    if unit == "m":
        return pd.Timedelta(minutes=count)
    if unit == "h":
        return pd.Timedelta(hours=count)
    if unit == "d":
        return pd.Timedelta(days=count)
    if unit == "w":
        return pd.Timedelta(weeks=count)
    return None


def _read_flow_ts(path: Path) -> pd.DatetimeIndex:
    if not path.exists():
        return pd.DatetimeIndex([])
    try:
        df = pd.read_parquet(path)
    except Exception:
        return pd.DatetimeIndex([])
    if df.empty:
        return pd.DatetimeIndex([])

    cols = {str(c).lower(): c for c in df.columns}
    ts_col = None
    for candidate in ("ts", "timestamp", "datetime", "date"):
        if candidate in cols:
            ts_col = cols[candidate]
            break
    if ts_col is not None:
        ts = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
    else:
        ts = pd.to_datetime(df.index, utc=True, errors="coerce")
    ts = ts.dropna().drop_duplicates().sort_values()
    return pd.DatetimeIndex(ts)


def _repair_flow_gaps(path: Path, interval: str) -> bool:
    if not path.exists():
        return False
    step = _parse_interval(interval)
    if step is None:
        return False

    try:
        df = pd.read_parquet(path)
    except Exception:
        return False
    if df.empty:
        return False

    cols = {str(c).lower(): c for c in df.columns}
    ts_col = None
    for candidate in ("ts", "timestamp", "datetime", "date"):
        if candidate in cols:
            ts_col = cols[candidate]
            break

    if ts_col is None:
        ts = pd.to_datetime(df.index, utc=True, errors="coerce")
    else:
        ts = pd.to_datetime(df[ts_col], utc=True, errors="coerce")

    frame = df.copy()
    frame["__ts__"] = ts
    frame = frame.dropna(subset=["__ts__"]).drop_duplicates(subset=["__ts__"], keep="last")
    frame = frame.sort_values("__ts__").set_index("__ts__")
    if len(frame.index) < 2:
        return False

    start = pd.Timestamp(frame.index.min()).floor(interval)
    end = pd.Timestamp(frame.index.max()).ceil(interval)
    full_index = pd.date_range(start=start, end=end, freq=step, tz="UTC")

    if len(full_index) <= len(frame.index):
        return False

    repaired = frame.reindex(full_index)
    repaired = repaired.ffill().bfill()

    # Remove any existing time columns before inserting canonical index-derived time.
    time_like_cols = [
        c for c in repaired.columns if str(c).lower() in {"ts", "timestamp", "datetime", "date"}
    ]
    if time_like_cols:
        repaired = repaired.drop(columns=time_like_cols)

    repaired.insert(0, "ts", repaired.index)

    # Keep the original ts column name when present to preserve downstream schema expectations.
    if ts_col is not None and ts_col != "ts":
        repaired = repaired.rename(columns={"ts": ts_col})

    repaired.to_parquet(path, index=False)
    return True


def _resolve_flow_dirs(out_dir: Path, flow_dir: str | None) -> list[Path]:
    candidates: list[Path] = []
    if flow_dir:
        candidates.append(Path(flow_dir).expanduser())
    candidates.append(out_dir / "flow")
    default_flow = ROOT / "data" / "flow"
    if default_flow not in candidates:
        candidates.append(default_flow)

    seen: set[Path] = set()
    resolved: list[Path] = []
    for candidate in candidates:
        path = candidate.resolve()
        if path in seen:
            continue
        seen.add(path)
        resolved.append(path)
    return resolved


def _compute_missing_flow_rows(
    flow_dirs: list[Path],
    interval: str,
    diagnostics: dict[str, Any],
    repair_gaps: bool,
) -> tuple[int, dict[str, Any]]:
    per_symbol = diagnostics.get("symbols", {}) if isinstance(diagnostics, dict) else {}
    if not isinstance(per_symbol, dict):
        per_symbol = {}

    step = _parse_interval(interval)
    total_missing = 0
    details: dict[str, Any] = {}

    for symbol, stats in per_symbol.items():
        expected = 0
        if isinstance(stats, dict):
            expected = int(stats.get("rows_train", 0) or 0) + int(stats.get("rows_oos", 0) or 0)

        normalized = _normalize_symbol(symbol)
        flow_name = f"{normalized}_{interval}.parquet"
        searched = [str(flow_dir / flow_name) for flow_dir in flow_dirs]
        flow_path = next((flow_dir / flow_name for flow_dir in flow_dirs if (flow_dir / flow_name).exists()), flow_dirs[0] / flow_name)

        repaired = False
        if repair_gaps:
            repaired = _repair_flow_gaps(flow_path, interval=interval)

        ts = _read_flow_ts(flow_path)
        actual = int(len(ts))

        row_deficit = max(0, expected - actual) if expected > 0 else 0
        gap_missing = 0
        if step is not None and len(ts) > 1:
            diffs = pd.Series(ts[1:] - ts[:-1])
            for gap in diffs:
                if gap > step:
                    gap_missing += max(0, int(gap / step) - 1)

        symbol_missing = int(row_deficit + gap_missing)
        total_missing += symbol_missing
        details[symbol] = {
            "normalized": normalized,
            "flow_path": str(flow_path),
            "searched_paths": searched,
            "repaired": bool(repaired),
            "expected_rows": int(expected),
            "actual_rows": int(actual),
            "row_deficit": int(row_deficit),
            "gap_missing": int(gap_missing),
            "missing_rows": int(symbol_missing),
        }

    return int(total_missing), details


def _family_from_event(event_name: str) -> str:
    token = str(event_name or "").strip().lower()
    if not token:
        return "unknown"
    parts = [p for p in token.split("_") if p]
    if len(parts) >= 2 and parts[0] == "edge":
        return parts[1]
    return parts[0]


def _promotion_diagnostics(
    *,
    validation: dict[str, Any],
    registry: dict[str, Any],
    diagnostics: dict[str, Any],
    rejected_edges: list[dict[str, Any]],
    promotion_readiness: dict[str, Any],
) -> dict[str, Any]:
    promotion = validation.get("promotion", {}) if isinstance(validation, dict) else {}
    checks = promotion.get("checks", {}) if isinstance(promotion, dict) else {}
    checks = checks if isinstance(checks, dict) else {}

    failed_gates = sorted([str(k) for k, v in checks.items() if not bool(v)])

    reasons = Counter()
    reason_examples: dict[str, dict[str, Any]] = {}
    family_counts = Counter()
    symbol_counts = Counter()

    for row in rejected_edges:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "unknown") or "unknown")
        symbol_counts[symbol] += 1

        event_name = str(row.get("event", "") or "")
        family_counts[_family_from_event(event_name)] += 1

        raw_reason = row.get("reason", [])
        reason_tokens = raw_reason if isinstance(raw_reason, list) else [raw_reason]
        reason_tokens = [str(x) for x in reason_tokens if str(x).strip()]
        if not reason_tokens:
            reason_tokens = ["unknown"]

        for reason in reason_tokens:
            reasons[reason] += 1
            if reason not in reason_examples:
                reason_examples[reason] = {
                    "symbol": symbol,
                    "event": event_name,
                    "samples": row.get("samples", None),
                }

    top_reasons = [
        {
            "reason": reason,
            "count": int(count),
            "example": reason_examples.get(reason, {}),
        }
        for reason, count in reasons.most_common(10)
    ]

    recommended_actions: list[str] = []
    if reasons.get("insufficient_event_samples", 0) > 0:
        recommended_actions.append(
            "Increase lookback and/or broaden symbol universe to raise event sample counts."
        )
    if reasons.get("no_event_triggers", 0) > 0:
        recommended_actions.append(
            "Review event definitions with high zero-trigger rates and relax trigger strictness for shadow-only validation."
        )
    if "trade_count" in failed_gates:
        recommended_actions.append(
            "Prioritize generating edges with higher expected trade frequency before tightening profitability filters."
        )
    if "walk_forward_consistency" in failed_gates or "regime_stability" in failed_gates:
        recommended_actions.append(
            "Run robustness tuning focused on regime coverage and walk-forward stability, then re-evaluate promotion checks."
        )
    if "live_shadow_gate" in failed_gates:
        recommended_actions.append(
            "Continue paper/shadow run until live shadow thresholds are met for the required duration."
        )
    if not recommended_actions:
        recommended_actions.append("No dominant blocker identified; inspect top rejection examples and gate details.")

    accepted_edges = len(registry.get("edges", [])) if isinstance(registry, dict) else 0
    eligible_edges = len(promotion_readiness.get("eligible_edge_ids", [])) if isinstance(promotion_readiness, dict) else 0

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "blocked" if failed_gates else "pass",
        "failure_summary": diagnostics.get("failure_summary", "unknown"),
        "promotion": {
            "approved": bool(promotion.get("approved", False)) if isinstance(promotion, dict) else False,
            "failed_gates": failed_gates,
            "gate_checks": checks,
        },
        "edge_counts": {
            "accepted": int(accepted_edges),
            "eligible": int(eligible_edges),
            "rejected": int(len(rejected_edges)),
        },
        "rejection_summary": {
            "top_reasons": top_reasons,
            "reason_counts": dict(reasons),
            "symbol_counts": dict(symbol_counts),
            "family_counts": dict(family_counts),
        },
        "recommended_actions": recommended_actions,
    }


def _edge_count(registry: dict[str, Any]) -> int:
    if not isinstance(registry, dict):
        return 0
    edges = registry.get("edges", [])
    return len(edges) if isinstance(edges, list) else 0


def _adaptive_discovery_profiles(args: argparse.Namespace) -> list[dict[str, int]]:
    return [
        {
            "min_event_samples": int(args.relaxed_min_event_samples),
            "min_segment_samples": int(args.relaxed_min_segment_samples),
            "min_assets": int(args.relaxed_min_assets),
        },
        {"min_event_samples": 90, "min_segment_samples": 90, "min_assets": 1},
        {"min_event_samples": 70, "min_segment_samples": 70, "min_assets": 1},
        {"min_event_samples": 50, "min_segment_samples": 50, "min_assets": 1},
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Capital-readiness deployment pipeline")
    parser.add_argument("--period", default="180d")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--symbol", default="BTC-USD")
    parser.add_argument("--output-dir", default="data")
    parser.add_argument("--flow-dir", default=None)
    parser.add_argument("--repair-flow-gaps", action="store_true")
    parser.add_argument("--auto-relaxed-rerun", action="store_true")
    parser.add_argument("--relaxed-min-event-samples", type=int, default=120)
    parser.add_argument("--relaxed-min-segment-samples", type=int, default=120)
    parser.add_argument("--relaxed-min-assets", type=int, default=1)
    parser.add_argument("--target-min-accepted-edges", type=int, default=1)
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    discovery_profile: dict[str, Any] = {
        "name": "strict_default",
        "min_event_samples": None,
        "min_segment_samples": None,
        "min_assets": None,
        "fallback_triggered": False,
        "attempts": [],
    }
    _run_discovery(period=args.period, interval=args.interval, out_dir=str(out_dir))

    registry = _load_json(out_dir / "edge_registry.json")
    rejected_edges = _load_json(out_dir / "rejected_edges.json")
    if not isinstance(rejected_edges, list):
        rejected_edges = []
    diagnostics = _load_json(out_dir / "discovery_diagnostics.json")
    promotion_readiness = _load_json(out_dir / "promotion_readiness.json")
    if not isinstance(promotion_readiness, dict):
        promotion_readiness = {}

    accepted_edges = _edge_count(registry)
    if accepted_edges < max(1, int(args.target_min_accepted_edges)) and bool(args.auto_relaxed_rerun):
        discovery_profile["fallback_triggered"] = True
        target_edges = max(1, int(args.target_min_accepted_edges))
        for i, profile in enumerate(_adaptive_discovery_profiles(args), start=1):
            _run_discovery(
                period=args.period,
                interval=args.interval,
                out_dir=str(out_dir),
                min_event_samples=int(profile["min_event_samples"]),
                min_segment_samples=int(profile["min_segment_samples"]),
                min_assets=int(profile["min_assets"]),
            )
            registry = _load_json(out_dir / "edge_registry.json")
            rejected_edges = _load_json(out_dir / "rejected_edges.json")
            if not isinstance(rejected_edges, list):
                rejected_edges = []
            diagnostics = _load_json(out_dir / "discovery_diagnostics.json")
            promotion_readiness = _load_json(out_dir / "promotion_readiness.json")
            if not isinstance(promotion_readiness, dict):
                promotion_readiness = {}

            accepted_edges = _edge_count(registry)
            discovery_profile["attempts"].append(
                {
                    "attempt": i,
                    **profile,
                    "accepted_edges": int(accepted_edges),
                }
            )
            discovery_profile.update(
                {
                    "name": "adaptive_relaxed_sweep",
                    "min_event_samples": int(profile["min_event_samples"]),
                    "min_segment_samples": int(profile["min_segment_samples"]),
                    "min_assets": int(profile["min_assets"]),
                }
            )
            if accepted_edges >= target_edges:
                break
    shadow = _load_shadow_artifact(out_dir)
    allocator_snapshot = _load_json(out_dir / "allocator_snapshot.json")
    lifecycle_snapshot = _load_json(out_dir / "edge_lifecycle.json")
    registry_lifecycle = registry.get("lifecycle", {}) if isinstance(registry, dict) else {}
    if not lifecycle_snapshot:
        lifecycle_snapshot = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "lifecycle": registry_lifecycle,
        }

    versioning = RegistryVersioning(base_dir=ROOT / "registry" / "versions")
    version_info = versioning.persist(registry, diagnostics=diagnostics)

    engine = AlphaValidationEngine(fee_bps=6.0, slippage_bps=5.0)
    df = _download_ohlcv(args.symbol, period=args.period, interval=args.interval)
    if df.empty:
        validation = {"error": "missing_validation_data"}
    else:
        df_eval = df.tail(900)
        bt, trades = engine.run_backtest(df_eval)
        wf = engine.walk_forward(df_eval, windows=4)
        regime = engine.regime_segmented_backtest(df_eval)
        mc = engine.monte_carlo(trades, n_paths=250)
        flow_ablation = engine.compare_with_without_flow(df_eval)
        validation = {
            "backtest": _serialize_backtest(bt),
            "walk_forward": wf,
            "regime": regime,
            "monte_carlo": mc,
            "flow_ablation": flow_ablation,
            "promotion": engine.promotion_criteria(bt, wf, regime, live_shadow=shadow),
        }

    flow_dirs = _resolve_flow_dirs(out_dir=out_dir, flow_dir=args.flow_dir)
    missing_flow_rows, flow_quality_details = _compute_missing_flow_rows(
        flow_dirs=flow_dirs,
        interval=args.interval,
        diagnostics=diagnostics,
        repair_gaps=bool(args.repair_flow_gaps),
    )

    exposure = {
        "net_exposure": 0.0,
        "gross_exposure": 0.0,
    }
    data_quality = {
        "missing_flow_rows": int(missing_flow_rows),
    }
    failure_diag = FailureDiagnostics.analyze(
        edge_report=registry,
        exposure_report=exposure,
        data_quality=data_quality,
    )

    if "flow_ablation" in validation:
        (out_dir / "with_without_flow_report.json").write_text(
            json.dumps(validation["flow_ablation"], indent=2),
            encoding="utf-8",
        )
    (out_dir / "flow_quality_report.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "interval": args.interval,
                "flow_dirs": [str(p) for p in flow_dirs],
                "repair_flow_gaps": bool(args.repair_flow_gaps),
                "missing_flow_rows": int(missing_flow_rows),
                "symbols": flow_quality_details,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    (out_dir / "allocator_snapshot.json").write_text(
        json.dumps(allocator_snapshot, indent=2),
        encoding="utf-8",
    )
    (out_dir / "edge_lifecycle.json").write_text(
        json.dumps(lifecycle_snapshot, indent=2),
        encoding="utf-8",
    )

    traceability = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline": [
            "edge_discovery",
            "registry_versioning",
            "portfolio_allocator",
            "execution_engine",
            "monitoring",
        ],
        "registry_version": version_info,
        "artifacts": {
            "registry": str(out_dir / "edge_registry.json"),
            "rejected": str(out_dir / "rejected_edges.json"),
            "top_edges": str(out_dir / "top_edges.csv"),
            "diagnostics": str(out_dir / "discovery_diagnostics.json"),
            "promotion_diagnostics": str(out_dir / "promotion_diagnostics.json"),
            "shadow_performance": str(out_dir / "shadow_performance.json"),
            "flow_ablation": str(out_dir / "with_without_flow_report.json"),
            "allocator_snapshot": str(out_dir / "allocator_snapshot.json"),
            "edge_lifecycle": str(out_dir / "edge_lifecycle.json"),
        },
    }

    (out_dir / "validation_upgrade.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    (out_dir / "failure_diagnostics.json").write_text(json.dumps(failure_diag, indent=2), encoding="utf-8")
    (out_dir / "deployment_traceability.json").write_text(json.dumps(traceability, indent=2), encoding="utf-8")

    promotion_diagnostics = _promotion_diagnostics(
        validation=validation,
        registry=registry,
        diagnostics=diagnostics,
        rejected_edges=rejected_edges,
        promotion_readiness=promotion_readiness,
    )
    promotion_diagnostics["discovery_profile"] = discovery_profile
    (out_dir / "promotion_diagnostics.json").write_text(
        json.dumps(promotion_diagnostics, indent=2),
        encoding="utf-8",
    )

    promotion_obj = validation.get("promotion") if isinstance(validation, dict) else {}
    if not isinstance(promotion_obj, dict):
        promotion_obj = {}
    if not isinstance(version_info, dict):
        version_info = {}

    print(json.dumps({
        "status": "completed",
        "version": version_info.get("version", ""),
        "promotion_approved": bool(promotion_obj.get("approved", False)),
        "failed_promotion_gates": promotion_diagnostics.get("promotion", {}).get("failed_gates", []),
        "failure_status": failure_diag.get("status", "unknown"),
    }, indent=2))


if __name__ == "__main__":
    main()
