from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
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


def _run_discovery(period: str, interval: str, out_dir: str) -> None:
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


def _compute_missing_flow_rows(out_dir: Path, interval: str, diagnostics: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    per_symbol = diagnostics.get("symbols", {}) if isinstance(diagnostics, dict) else {}
    if not isinstance(per_symbol, dict):
        per_symbol = {}

    flow_dir = out_dir / "flow"
    step = _parse_interval(interval)
    total_missing = 0
    details: dict[str, Any] = {}

    for symbol, stats in per_symbol.items():
        expected = 0
        if isinstance(stats, dict):
            expected = int(stats.get("rows_train", 0) or 0) + int(stats.get("rows_oos", 0) or 0)

        normalized = _normalize_symbol(symbol)
        flow_path = flow_dir / f"{normalized}_{interval}.parquet"
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
            "expected_rows": int(expected),
            "actual_rows": int(actual),
            "row_deficit": int(row_deficit),
            "gap_missing": int(gap_missing),
            "missing_rows": int(symbol_missing),
        }

    return int(total_missing), details


def main() -> None:
    parser = argparse.ArgumentParser(description="Capital-readiness deployment pipeline")
    parser.add_argument("--period", default="180d")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--symbol", default="BTC-USD")
    parser.add_argument("--output-dir", default="data")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    _run_discovery(period=args.period, interval=args.interval, out_dir=str(out_dir))

    registry = _load_json(out_dir / "edge_registry.json")
    diagnostics = _load_json(out_dir / "discovery_diagnostics.json")
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

    missing_flow_rows, flow_quality_details = _compute_missing_flow_rows(
        out_dir=out_dir,
        interval=args.interval,
        diagnostics=diagnostics,
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
            "shadow_performance": str(out_dir / "shadow_performance.json"),
            "flow_ablation": str(out_dir / "with_without_flow_report.json"),
            "allocator_snapshot": str(out_dir / "allocator_snapshot.json"),
            "edge_lifecycle": str(out_dir / "edge_lifecycle.json"),
        },
    }

    (out_dir / "validation_upgrade.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    (out_dir / "failure_diagnostics.json").write_text(json.dumps(failure_diag, indent=2), encoding="utf-8")
    (out_dir / "deployment_traceability.json").write_text(json.dumps(traceability, indent=2), encoding="utf-8")

    promotion_obj = validation.get("promotion") if isinstance(validation, dict) else {}
    if not isinstance(promotion_obj, dict):
        promotion_obj = {}
    if not isinstance(version_info, dict):
        version_info = {}

    print(json.dumps({
        "status": "completed",
        "version": version_info.get("version", ""),
        "promotion_approved": bool(promotion_obj.get("approved", False)),
        "failure_status": failure_diag.get("status", "unknown"),
    }, indent=2))


if __name__ == "__main__":
    main()
