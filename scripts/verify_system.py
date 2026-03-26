from __future__ import annotations

import argparse
import json
import os
from typing import Any

import requests

from backend.src.platform.db import Database
from backend.src.platform.repository import ensure_schema, get_pipeline_counts


def _api_get(base_url: str, path: str) -> tuple[bool, dict[str, Any]]:
    try:
        response = requests.get(f"{base_url.rstrip('/')}{path}", timeout=10)
        data = response.json() if response.content else {}
        return bool(response.status_code < 400), data
    except Exception as exc:
        return False, {"error": str(exc)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify end-to-end system runtime health and persistence")
    parser.add_argument("--api-url", default=os.getenv("VERIFY_API_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument("--require-trades", action="store_true", help="Fail if trades table has zero rows")
    args = parser.parse_args()

    report: dict[str, Any] = {
        "api_url": args.api_url,
        "checks": {},
        "pipeline_counts": {},
        "status": "unknown",
    }

    ok_health, health = _api_get(args.api_url, "/health")
    report["checks"]["health"] = {"ok": ok_health, "payload": health}

    ok_ready, ready = _api_get(args.api_url, "/health/ready")
    report["checks"]["health_ready"] = {"ok": ok_ready, "payload": ready}

    ok_deep, deep = _api_get(args.api_url, "/health/deep")
    report["checks"]["health_deep"] = {"ok": ok_deep, "payload": deep}

    ok_metrics, metrics = _api_get(args.api_url, "/metrics")
    report["checks"]["metrics"] = {"ok": ok_metrics, "payload": metrics}

    db_ok = False
    if args.database_url:
        db = None
        try:
            db = Database(args.database_url)
            ensure_schema(db)
            counts = get_pipeline_counts(db)
            report["pipeline_counts"] = counts
            db_ok = True
        except Exception as exc:
            report["checks"]["database"] = {"ok": False, "error": str(exc)}
        finally:
            if db is not None:
                db.close()
    else:
        report["checks"]["database"] = {"ok": False, "error": "DATABASE_URL not provided"}

    checks_ok = ok_health and ok_ready and ok_deep and ok_metrics and db_ok
    trades_ok = True
    if args.require_trades:
        trades_ok = float(report.get("pipeline_counts", {}).get("trades", 0.0) or 0.0) > 0.0

    report["status"] = "ok" if (checks_ok and trades_ok) else "failed"
    print(json.dumps(report, indent=2))

    if report["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
