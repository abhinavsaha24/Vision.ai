from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    parse_failures = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                parse_failures += 1
                logger.warning("telemetry_json_parse_failed err=%s line=%s", exc, line[:200])
                continue
    if parse_failures:
        logger.warning("telemetry_json_parse_failures_total=%s path=%s", parse_failures, path)
    return rows


def _safe_mean(xs: list[float]) -> float:
    if not xs:
        return 0.0
    return float(sum(xs) / len(xs))


def _safe_std(xs: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = _safe_mean(xs)
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return float(var ** 0.5)


def _build_family_validation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    observations = [r for r in rows if r.get("type") == "event_observation"]
    outcomes = [r for r in rows if r.get("type") == "event_outcome"]

    obs_by_id: dict[str, list[dict[str, Any]]] = {}
    for obs in observations:
        event_id = str(obs.get("event_id", ""))
        if not event_id:
            continue
        obs_by_id.setdefault(event_id, []).append(obs)

    outcome_by_event_h: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for out in outcomes:
        event_id = str(out.get("event_id", ""))
        if not event_id:
            continue
        try:
            horizon = int(out.get("horizon_s", 0) or 0)
            val = float(out.get("realized_edge_bps", 0.0) or 0.0)
        except Exception:
            continue
        if horizon > 0:
            outcome_by_event_h[event_id][horizon].append(val)

    family_obs_count: dict[str, int] = defaultdict(int)
    family_rejections: dict[str, int] = defaultdict(int)
    family_expected: dict[str, list[float]] = defaultdict(list)
    family_horizon_vals: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))

    for event_id, obs_items in obs_by_id.items():
        obs = obs_items[-1]
        event_type = str(obs.get("event_type", "unknown"))
        family_obs_count[event_type] += 1
        try:
            family_expected[event_type].append(float(obs.get("expected_edge_bps", 0.0) or 0.0))
        except Exception:
            pass

        for horizon, vals in outcome_by_event_h.get(event_id, {}).items():
            family_horizon_vals[event_type][horizon].extend(vals)

    for row in rows:
        if row.get("type") != "event_decision":
            continue
        if str(row.get("decision", "")) not in {"rejected", "no_trade"}:
            continue
        family = str(row.get("event_type", "unknown"))
        family_rejections[family] += 1

    families: dict[str, Any] = {}
    for family, count in family_obs_count.items():
        h_vals = family_horizon_vals.get(family, {})
        h_summary: dict[str, Any] = {}
        for h in (1, 5, 10, 30):
            vals = [float(v) for v in h_vals.get(h, [])]
            h_summary[str(h)] = {
                "samples": int(len(vals)),
                "expectancy_bps": _safe_mean(vals),
                "win_rate": float(sum(1 for v in vals if v > 0) / len(vals)) if vals else 0.0,
                "std_bps": _safe_std(vals),
            }

        vals_5 = [float(v) for v in h_vals.get(5, [])]
        pos = sum(1 for v in vals_5 if v > 0)
        neg = sum(1 for v in vals_5 if v < 0)
        asymmetry = float((pos - neg) / max(1, len(vals_5)))
        stability = 0.0
        if vals_5:
            stability = float(max(0.0, 1.0 - min(1.0, _safe_std(vals_5) / max(abs(_safe_mean(vals_5)), 1e-9))))

        accepted = int(count)
        rejected = int(family_rejections.get(family, 0))
        families[family] = {
            "event_frequency": accepted,
            "decision_rejections": rejected,
            "rejection_rate": float(rejected / max(1, accepted + rejected)),
            "expected_edge_bps": _safe_mean([float(x) for x in family_expected.get(family, [])]),
            "horizon_metrics": h_summary,
            "asymmetry_5s": asymmetry,
            "stability_5s": stability,
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "families": families,
        "summary": {
            "event_observations": int(len(observations)),
            "event_outcomes": int(len(outcomes)),
        },
    }


def _edge_emergence(validation: dict[str, Any], cost_bps: float, min_samples: int) -> dict[str, Any]:
    families = validation.get("families", {}) if isinstance(validation, dict) else {}
    candidates: list[dict[str, Any]] = []

    for family, row in families.items():
        if not isinstance(row, dict):
            continue
        h = row.get("horizon_metrics", {})
        h5 = h.get("5", {}) if isinstance(h, dict) else {}
        samples = int(h5.get("samples", 0) or 0)
        expectancy = float(h5.get("expectancy_bps", 0.0) or 0.0)
        stability = float(row.get("stability_5s", 0.0) or 0.0)
        net = expectancy - float(cost_bps)
        if samples < min_samples:
            continue
        candidates.append(
            {
                "family": family,
                "samples_5s": samples,
                "expectancy_5s_bps": expectancy,
                "expectancy_after_cost_bps": net,
                "stability_5s": stability,
                "survives_after_cost": bool(net > 0.0 and stability >= 0.2),
            }
        )

    candidates.sort(key=lambda x: float(x.get("expectancy_after_cost_bps", 0.0)), reverse=True)
    survivors = [c for c in candidates if bool(c.get("survives_after_cost", False))]

    if not survivors:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "no_edge",
            "message": "NO EDGE - INSUFFICIENT REAL MARKET EVIDENCE",
            "cost_bps": float(cost_bps),
            "min_samples": int(min_samples),
            "top_families": candidates[:5],
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "edge_candidates_present",
        "cost_bps": float(cost_bps),
        "min_samples": int(min_samples),
        "top_families": candidates[:5],
        "survivors": survivors[:5],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze runtime event telemetry and edge emergence")
    parser.add_argument("--input", default="data/live_alpha_signals.jsonl")
    parser.add_argument("--validation-output", default="data/event_family_validation.json")
    parser.add_argument("--emergence-output", default="data/edge_emergence_test.json")
    parser.add_argument("--cost-bps", type=float, default=1.5)
    parser.add_argument("--min-samples", type=int, default=5)
    args = parser.parse_args()

    rows = _load_jsonl(Path(args.input))
    validation = _build_family_validation(rows)
    emergence = _edge_emergence(validation, cost_bps=float(args.cost_bps), min_samples=int(args.min_samples))

    vpath = Path(args.validation_output)
    epath = Path(args.emergence_output)
    vpath.parent.mkdir(parents=True, exist_ok=True)
    epath.parent.mkdir(parents=True, exist_ok=True)

    vpath.write_text(json.dumps(validation, indent=2), encoding="utf-8")
    epath.write_text(json.dumps(emergence, indent=2), encoding="utf-8")

    print(f"validation_report={vpath}")
    print(f"emergence_report={epath}")
    print(json.dumps(emergence, indent=2))


if __name__ == "__main__":
    main()
