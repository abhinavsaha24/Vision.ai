from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if ROOT.as_posix() not in sys.path:
    sys.path.insert(0, ROOT.as_posix())

from backend.src.research.data_layer import (
    TimeSeriesStore,
    build_feature_table,
    collect_all_sources,
    run_data_validation,
    run_univariate_tests,
)
from backend.src.research.data_layer.schema import SourceConfig, UnivariateThresholds, ValidationThresholds


def run_pipeline(symbol: str, interval: str, lookback_hours: int, output_dir: Path, db_path: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    store = TimeSeriesStore(db_path)

    cross_assets = ["BTC-USD", "ETH-USD", "QQQ", "^GSPC"]
    config = SourceConfig(symbol=symbol, interval=interval, lookback_hours=lookback_hours)

    ingestion_stats = collect_all_sources(store, config, cross_assets=cross_assets)

    feature_table = build_feature_table(store, symbol=symbol, cross_assets=cross_assets)
    validation = run_data_validation(feature_table, ValidationThresholds())
    univariate = run_univariate_tests(feature_table, UnivariateThresholds())

    feature_path = output_dir / "alpha_feature_table.csv"
    report_path = output_dir / "alpha_data_layer_report.json"

    if not feature_table.empty:
        feature_table.sort_values("ts").to_csv(feature_path, index=False)

    report = {
        "status": "READY" if (validation.get("status") == "PASS") else "NOT_READY",
        "symbol": symbol,
        "interval": interval,
        "lookback_hours": lookback_hours,
        "db_path": db_path.as_posix(),
        "artifacts": {
            "feature_table_csv": feature_path.as_posix(),
            "report_json": report_path.as_posix(),
        },
        "ingestion": ingestion_stats,
        "feature_rows": int(len(feature_table)),
        "validation": validation,
        "univariate_tests": univariate,
    }

    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    store.close()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build institutional alpha data layer (data+features+validation+univariate testing)")
    parser.add_argument("--symbol", default="BTC-USD")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--lookback-hours", type=int, default=24 * 30)
    parser.add_argument("--output-dir", default="data")
    parser.add_argument("--db-path", default="data/alpha_timeseries.db")
    args = parser.parse_args()

    report = run_pipeline(
        symbol=args.symbol,
        interval=args.interval,
        lookback_hours=args.lookback_hours,
        output_dir=Path(args.output_dir),
        db_path=Path(args.db_path),
    )

    print("=== ALPHA DATA LAYER REPORT ===")
    print(
        json.dumps(
            {
                "status": report.get("status"),
                "feature_rows": report.get("feature_rows"),
                "validation_status": report.get("validation", {}).get("status"),
                "univariate_status": report.get("univariate_tests", {}).get("status"),
                "passing_features": [f.get("feature") for f in report.get("univariate_tests", {}).get("passing_features", [])],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
