from __future__ import annotations

import argparse
import json
from pathlib import Path

ALLOWED_STATUSES = {
    "do_not_trade_until_live_shadow_passes",
    "promotion_ready",
}


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"missing_file: {path}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"invalid_json_object: {path}")
    return obj


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate promotion readiness artifacts for CI")
    parser.add_argument("--readiness-path", required=True)
    parser.add_argument("--registry-path", required=True)
    args = parser.parse_args()

    readiness_path = Path(args.readiness_path)
    registry_path = Path(args.registry_path)

    readiness = _load_json(readiness_path)
    registry = _load_json(registry_path)

    status = str(readiness.get("status", "")).strip()
    if status not in ALLOWED_STATUSES:
        raise SystemExit(f"invalid_readiness_status: {status}")

    eligible_edge_ids = readiness.get("eligible_edge_ids", [])
    if not isinstance(eligible_edge_ids, list):
        raise SystemExit("eligible_edge_ids_must_be_list")

    registry_edges = registry.get("edges", [])
    if not isinstance(registry_edges, list):
        raise SystemExit("registry_edges_must_be_list")

    registry_edge_ids = {
        str(edge.get("edge_id", ""))
        for edge in registry_edges
        if isinstance(edge, dict) and str(edge.get("edge_id", ""))
    }

    for edge_id in eligible_edge_ids:
        if str(edge_id) not in registry_edge_ids:
            raise SystemExit(f"eligible_edge_missing_in_registry: {edge_id}")

    if status == "promotion_ready" and len(eligible_edge_ids) == 0:
        raise SystemExit("promotion_ready_requires_eligible_edge")

    result = {
        "status": status,
        "eligible_edge_count": len(eligible_edge_ids),
        "registry_edge_count": len(registry_edge_ids),
        "validation": "ok",
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
