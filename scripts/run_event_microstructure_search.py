from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.src.research.event_time_microstructure import EventResearchConfig, EventTimeMicrostructureEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="Event-time microstructure alpha discovery")
    parser.add_argument("--microstructure-root", default="data/microstructure")
    parser.add_argument("--output", default="data/event_microstructure_result.json")
    parser.add_argument("--diagnostics-output", default="data/event_microstructure_diagnostics.json")
    parser.add_argument("--coverage-output", default="data/event_microstructure_coverage_report.json")
    parser.add_argument("--rejection-summary-output", default="data/event_microstructure_rejection_summary.json")
    parser.add_argument("--train-fraction", type=float, default=0.70)
    parser.add_argument("--min-event-samples", type=int, default=200)
    parser.add_argument("--min-oos-samples", type=int, default=120)
    parser.add_argument("--min-oos-t-stat", type=float, default=2.0)
    parser.add_argument("--min-oos-profit-factor", type=float, default=1.2)
    parser.add_argument("--fee-bps", type=float, default=0.9)
    parser.add_argument("--latency-penalty-bps", type=float, default=0.8)
    parser.add_argument("--slippage-coef-bps", type=float, default=2.2)
    parser.add_argument("--min-capture-hours", type=float, default=12.0)
    parser.add_argument("--min-overlap-hours", type=float, default=12.0)
    parser.add_argument("--min-symbol-capture-hours", type=float, default=12.0)
    parser.add_argument("--max-gap-ms", type=int, default=3000)
    parser.add_argument("--min-total-micro-events", type=int, default=150000)
    parser.add_argument("--min-trades-per-hour", type=float, default=3000.0)
    parser.add_argument("--min-books-per-hour", type=float, default=12000.0)
    parser.add_argument("--max-sequence-break-rate", type=float, default=0.005)
    args = parser.parse_args()

    engine = EventTimeMicrostructureEngine(
        EventResearchConfig(
            train_fraction=float(args.train_fraction),
            min_event_samples=int(args.min_event_samples),
            min_oos_samples=int(args.min_oos_samples),
            min_oos_t_stat=float(args.min_oos_t_stat),
            min_oos_profit_factor=float(args.min_oos_profit_factor),
            fee_bps=float(args.fee_bps),
            latency_penalty_bps=float(args.latency_penalty_bps),
            slippage_coef_bps=float(args.slippage_coef_bps),
            min_capture_hours=float(args.min_capture_hours),
            min_overlap_hours=float(args.min_overlap_hours),
            min_symbol_capture_hours=float(args.min_symbol_capture_hours),
            max_gap_ms=int(args.max_gap_ms),
            min_total_micro_events=int(args.min_total_micro_events),
            min_trades_per_hour=float(args.min_trades_per_hour),
            min_books_per_hour=float(args.min_books_per_hour),
            max_sequence_break_rate=float(args.max_sequence_break_rate),
        )
    )

    result = engine.discover(args.microstructure_root)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    diagnostics = {
        "metrics": result.get("metrics", {}) if isinstance(result, dict) else {},
        "event_counts": (result.get("metrics", {}) or {}).get("event_types", {}),
        "rejected": result.get("rejected", []) if isinstance(result, dict) else [],
        "missing_components": [
            str(r) for item in (result.get("rejected", []) if isinstance(result, dict) else []) for r in (item.get("reason", []) if isinstance(item, dict) else [])
        ],
    }
    diagnostics_out = Path(args.diagnostics_output)
    diagnostics_out.parent.mkdir(parents=True, exist_ok=True)
    diagnostics_out.write_text(json.dumps(diagnostics, indent=2, default=str), encoding="utf-8")

    metrics = result.get("metrics", {}) if isinstance(result, dict) else {}
    rejected = result.get("rejected", []) if isinstance(result, dict) else []

    coverage_report = {
        "status": str(metrics.get("status", "unknown")),
        "capture_hours": float(metrics.get("capture_hours", 0.0) or 0.0),
        "overlap_hours": float(metrics.get("overlap_hours", 0.0) or 0.0),
        "min_symbol_capture_hours": float(metrics.get("min_symbol_capture_hours", 0.0) or 0.0),
        "max_observed_gap_ms": int(metrics.get("max_observed_gap_ms", 0) or 0),
        "has_trade_orderbook_overlap": bool(metrics.get("has_trade_orderbook_overlap", False)),
        "trade_frequency_per_hour": float(metrics.get("trade_frequency_per_hour", 0.0) or 0.0),
        "orderbook_update_rate_per_hour": float(metrics.get("orderbook_update_rate_per_hour", 0.0) or 0.0),
        "event_density_per_hour": float(metrics.get("event_density_per_hour", 0.0) or 0.0),
        "total_micro_events": int(metrics.get("total_micro_events", 0) or 0),
        "sequence_break_rate": float(metrics.get("sequence_break_rate", 0.0) or 0.0),
        "sequence_continuity": bool(metrics.get("sequence_continuity", False)),
    }

    reason_counts: dict[str, int] = {}
    for item in rejected:
        if not isinstance(item, dict):
            continue
        reasons = item.get("reason", [])
        if not isinstance(reasons, list):
            continue
        for reason in reasons:
            key = str(reason)
            reason_counts[key] = int(reason_counts.get(key, 0) + 1)

    rejection_summary = {
        "status": str(metrics.get("status", "unknown")),
        "rejected_count": int(len(rejected)),
        "reasons": reason_counts,
        "missing_information_dimension": str(metrics.get("missing_information_dimension", "unknown")),
        "minimal_upgrade": str(metrics.get("minimal_upgrade", "unknown")),
    }

    coverage_out = Path(args.coverage_output)
    coverage_out.parent.mkdir(parents=True, exist_ok=True)
    coverage_out.write_text(json.dumps(coverage_report, indent=2, default=str), encoding="utf-8")

    rejection_out = Path(args.rejection_summary_output)
    rejection_out.parent.mkdir(parents=True, exist_ok=True)
    rejection_out.write_text(json.dumps(rejection_summary, indent=2, default=str), encoding="utf-8")

    top_edges = result.get("top_edges", []) if isinstance(result, dict) else []
    status = str(metrics.get("status", "")).strip().lower()

    not_ready_statuses = {
        "capture_not_ready",
        "no_microstructure_data",
        "no_events_detected",
        "missing_event_dimensions",
    }
    if status in not_ready_statuses:
        print("NO EDGE — INSUFFICIENT MICROSTRUCTURE DATA QUALITY")
        return

    if not top_edges:
        print("NO EDGE — MARKET INEFFICIENT AT CURRENT RESOLUTION")
        return

    payload = {
        "top_edges": top_edges,
        "metrics": result.get("metrics", {}),
        "output": str(out),
    }
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
