from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


logger = logging.getLogger(__name__)


def _run(cmd: list[str]) -> None:
    timeout_sec = 120
    try:
        subprocess.run(cmd, check=True, timeout=timeout_sec, capture_output=True, text=True)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"midfreq_subprocess_timeout cmd={cmd} timeout={timeout_sec}s stdout={exc.stdout} stderr={exc.stderr}"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"midfreq_subprocess_failed cmd={cmd} returncode={exc.returncode} stdout={exc.stdout} stderr={exc.stderr}"
        ) from exc


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.warning("midfreq_json_decode_failed path=%s err=%s", path, exc)
        return {}


def _collect_for_interval(
    interval: str,
    period: str,
    symbols: list[str],
    output_root: Path,
) -> dict[str, Any]:
    interval_dir = output_root / interval
    flow_dir = interval_dir / "flow"
    research_dir = interval_dir / "research"
    interval_dir.mkdir(parents=True, exist_ok=True)

    _run(
        [
            sys.executable,
            str(ROOT / "scripts" / "collect_flow_data.py"),
            "--symbols",
            *symbols,
            "--period",
            period,
            "--interval",
            interval,
            "--output-dir",
            str(flow_dir),
            "--research-dir",
            str(research_dir),
        ]
    )

    _run(
        [
            sys.executable,
            str(ROOT / "scripts" / "discover_edge.py"),
            "--symbols",
            *symbols,
            "--period",
            period,
            "--interval",
            interval,
            "--output-dir",
            str(interval_dir),
            "--research-dir",
            str(research_dir),
            "--flow-dir",
            str(flow_dir),
        ]
    )

    registry = _load_json(interval_dir / "edge_registry.json")
    diagnostics = _load_json(interval_dir / "discovery_diagnostics.json")
    top5 = _load_json(interval_dir / "top_5_edges.json")
    edges = registry.get("edges", []) if isinstance(registry, dict) else []

    return {
        "interval": interval,
        "period": period,
        "accepted_edges": int(len(edges)),
        "top_edges": top5 if isinstance(top5, list) else [],
        "diagnostics": diagnostics,
        "registry_path": str(interval_dir / "edge_registry.json"),
    }


def _flatten_candidates(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for res in results:
        interval = str(res.get("interval", ""))
        for edge in res.get("top_edges", [])[:5]:
            if not isinstance(edge, dict):
                continue
            stats = edge.get("stats", {}) or {}
            oos = edge.get("oos_stats", {}) or {}
            rows.append(
                {
                    "interval": interval,
                    "edge_id": edge.get("edge_id", ""),
                    "event": edge.get("event", ""),
                    "assets": edge.get("assets", []),
                    "direction": edge.get("direction", ""),
                    "is": {
                        "expectancy": float(stats.get("expectancy", 0.0) or 0.0),
                        "profit_factor": float(stats.get("profit_factor", 0.0) or 0.0),
                        "t_stat": float(stats.get("t_stat", 0.0) or 0.0),
                        "samples": float(stats.get("samples", 0.0) or 0.0),
                        "cross_asset_stability": float(stats.get("cross_asset_stability", 0.0) or 0.0),
                    },
                    "oos": {
                        "expectancy": float(oos.get("expectancy", 0.0) or 0.0),
                        "profit_factor": float(oos.get("profit_factor", 0.0) or 0.0),
                        "t_stat": float(oos.get("t_stat", 0.0) or 0.0),
                        "samples": float(oos.get("samples", 0.0) or 0.0),
                    },
                    "trade_count": int(float(stats.get("samples", 0.0) or 0.0)),
                    "stability": {
                        "cross_asset_stability": float(stats.get("cross_asset_stability", 0.0) or 0.0),
                        "cross_asset_expectancy_std": float(stats.get("cross_asset_expectancy_std", 0.0) or 0.0),
                        "cross_asset_pf_std": float(stats.get("cross_asset_pf_std", 0.0) or 0.0),
                    },
                }
            )
    rows.sort(
        key=lambda r: (
            float(r["oos"]["expectancy"]),
            float(r["oos"]["t_stat"]),
            float(r["oos"]["profit_factor"]),
            float(r["is"]["cross_asset_stability"]),
        ),
        reverse=True,
    )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Run mid-frequency multi-resolution strict edge search")
    parser.add_argument("--symbols", nargs="+", default=["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD"])
    parser.add_argument("--output-root", default="data/midfreq_search")
    args = parser.parse_args()

    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    plan = [
        ("5m", "60d"),
        ("15m", "60d"),
        ("1h", "180d"),
    ]

    results: list[dict[str, Any]] = []
    for interval, period in plan:
        try:
            results.append(
                _collect_for_interval(
                    interval=interval,
                    period=period,
                    symbols=list(args.symbols),
                    output_root=output_root,
                )
            )
        except Exception as exc:
            results.append(
                {
                    "interval": interval,
                    "period": period,
                    "accepted_edges": 0,
                    "top_edges": [],
                    "diagnostics": {},
                    "registry_path": "",
                    "error": str(exc),
                }
            )

    candidates = _flatten_candidates(results)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results_by_interval": results,
        "top_candidates": candidates[:5],
    }

    out_file = output_root / "midfreq_edge_search_summary.json"
    out_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"summary={out_file}")

    if not candidates:
        print("NO EDGE — MARKET INEFFICIENT AT CURRENT RESOLUTION")
        return

    print(json.dumps(candidates[:5], indent=2))


if __name__ == "__main__":
    main()
