from __future__ import annotations

import numpy as np
import pandas as pd

from .schema import ValidationThresholds


def run_data_validation(feature_table: pd.DataFrame, thresholds: ValidationThresholds) -> dict:
    if feature_table.empty:
        return {"status": "FAILURE", "reason": "empty_feature_table"}

    df = feature_table.copy().sort_values("ts").reset_index(drop=True)
    ts = pd.to_datetime(df["ts"], utc=True, errors="coerce")

    missing_ratio = float(df.isna().mean().mean())

    deltas = ts.diff().dt.total_seconds().dropna()
    median_delta = float(deltas.median()) if not deltas.empty else 3600.0
    max_delta = float(deltas.max()) if not deltas.empty else median_delta
    timestamp_gap_ok = bool(max_delta <= (thresholds.max_timestamp_gap_factor * median_delta + 1e-9))

    # Alignment quality: all feature columns should have low average lag against canonical ts grid.
    canonical = pd.date_range(start=ts.min(), end=ts.max(), freq="1h", tz="UTC")
    canonical_df = pd.DataFrame({"ts": canonical})
    aligned = canonical_df.merge(df, on="ts", how="left")
    alignment_missing = float(aligned.isna().mean().mean())
    alignment_ok = bool(alignment_missing <= thresholds.max_missing_ratio)

    no_missing_ok = bool(missing_ratio <= thresholds.max_missing_ratio)
    passed = no_missing_ok and timestamp_gap_ok and alignment_ok

    return {
        "status": "PASS" if passed else "FAIL",
        "checks": {
            "no_missing_data": {
                "ok": no_missing_ok,
                "missing_ratio": missing_ratio,
                "threshold": thresholds.max_missing_ratio,
            },
            "timestamp_drift": {
                "ok": timestamp_gap_ok,
                "max_gap_seconds": max_delta,
                "median_gap_seconds": median_delta,
                "max_gap_factor_threshold": thresholds.max_timestamp_gap_factor,
            },
            "cross_source_alignment": {
                "ok": alignment_ok,
                "alignment_missing_ratio": alignment_missing,
                "threshold": thresholds.max_missing_ratio,
            },
        },
    }
