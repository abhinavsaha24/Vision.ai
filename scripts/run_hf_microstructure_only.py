from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class Metrics:
    samples: int
    expectancy: float
    t_stat: float
    sharpe: float
    win_rate: float


def _read_parquet_tree(root: Path) -> pd.DataFrame:
    files = sorted(root.rglob("*.parquet"))
    frames: list[pd.DataFrame] = []
    for fp in files:
        try:
            df = pd.read_parquet(fp)
        except Exception:
            continue
        if df is not None and not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, axis=0, ignore_index=True)
    return out


def _safe_std(x: np.ndarray) -> float:
    if x.size < 2:
        return 0.0
    v = float(np.std(x))
    return v if np.isfinite(v) else 0.0


def _metrics(x: np.ndarray) -> Metrics:
    if x.size == 0:
        return Metrics(0, 0.0, 0.0, 0.0, 0.0)
    mu = float(np.mean(x))
    sd = _safe_std(x)
    t = float((mu / (sd / np.sqrt(x.size))) if sd > 1e-12 else 0.0)
    sharpe = float((mu / sd) * np.sqrt(max(1.0, float(x.size)))) if sd > 1e-12 else 0.0
    wr = float(np.mean(x > 0.0))
    return Metrics(int(x.size), mu, t, sharpe, wr)


def _normalize_inputs(trades: pd.DataFrame, books: pd.DataFrame) -> pd.DataFrame:
    t = trades.copy()
    b = books.copy()

    t["ts"] = pd.to_datetime(t["exchange_ts_ms"], unit="ms", utc=True, errors="coerce")
    b["ts"] = pd.to_datetime(b["exchange_ts_ms"], unit="ms", utc=True, errors="coerce")
    t = t.dropna(subset=["ts"]).sort_values("ts")
    b = b.dropna(subset=["ts"]).sort_values("ts")

    t["signed_qty"] = np.where(t["side"].astype(str).str.lower().eq("buy"), pd.to_numeric(t["quantity"], errors="coerce").fillna(0.0), -pd.to_numeric(t["quantity"], errors="coerce").fillna(0.0))

    # Build 100ms event-time bars for seconds/sub-minute testing.
    t_bar = (
        t.set_index("ts")
        .groupby([pd.Grouper(freq="100ms"), "venue", "symbol"], dropna=False)
        .agg(
            signed_flow=("signed_qty", "sum"),
            trade_qty=("quantity", "sum"),
            trade_count=("quantity", "count"),
        )
        .reset_index()
    )

    b_bar = (
        b.set_index("ts")
        .groupby([pd.Grouper(freq="100ms"), "venue", "symbol"], dropna=False)
        .agg(
            mid_price=("mid_price", "last"),
            best_bid=("best_bid", "last"),
            best_ask=("best_ask", "last"),
            spread_bps=("spread_bps", "last"),
            queue_imbalance=("orderbook_imbalance", "last"),
            bid_depth=("bid_depth_top_n", "last"),
            ask_depth=("ask_depth_top_n", "last"),
        )
        .reset_index()
    )

    t_bar = t_bar.sort_values(["venue", "symbol", "ts"]).reset_index(drop=True)
    b_bar = b_bar.sort_values(["venue", "symbol", "ts"]).reset_index(drop=True)

    # Nearest-time alignment is required at HF because trades and depth updates rarely share exact bucket timestamps.
    parts: list[pd.DataFrame] = []
    keys = sorted(set(zip(b_bar["venue"], b_bar["symbol"])))
    for venue, symbol in keys:
        tb = t_bar[(t_bar["venue"] == venue) & (t_bar["symbol"] == symbol)].copy()
        bb = b_bar[(b_bar["venue"] == venue) & (b_bar["symbol"] == symbol)].copy()
        if tb.empty or bb.empty:
            continue
        tb = tb.sort_values("ts")
        bb = bb.sort_values("ts")
        merged = pd.merge_asof(
            bb,
            tb[["ts", "signed_flow", "trade_qty", "trade_count"]],
            on="ts",
            direction="backward",
            tolerance=pd.Timedelta(milliseconds=200),
        )
        merged["venue"] = venue
        merged["symbol"] = symbol
        parts.append(merged)

    m = pd.concat(parts, axis=0, ignore_index=True) if parts else pd.DataFrame()
    if m.empty:
        return m

    m = m.sort_values(["venue", "symbol", "ts"]).reset_index(drop=True)
    m["mid"] = pd.to_numeric(m["mid_price"], errors="coerce")
    m = m[np.isfinite(m["mid"]) & (m["mid"] > 0.0)].copy()
    m["spread_bps"] = pd.to_numeric(m["spread_bps"], errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0)
    m["spread_bps"] = m["spread_bps"].clip(lower=0.0, upper=80.0)

    # Drop pathological book updates (e.g., stale/partial snapshots) that create unrealistic microsecond jumps.
    m["mid_ret_100ms"] = m.groupby(["venue", "symbol"], dropna=False)["mid"].pct_change().replace([np.inf, -np.inf], np.nan)
    m = m[m["mid_ret_100ms"].abs().fillna(0.0) <= 0.10].copy()
    m = m.drop(columns=["mid_ret_100ms"]) 

    # Real microstructure features from true tick/orderbook feeds.
    m["ofi_real"] = pd.to_numeric(m["signed_flow"], errors="coerce").fillna(0.0)
    m["queue_imbalance_real"] = pd.to_numeric(m["queue_imbalance"], errors="coerce").fillna(0.0)
    m["spread_dynamics_real"] = pd.to_numeric(m["spread_bps"], errors="coerce").fillna(0.0).diff().fillna(0.0)

    return m


def _feature_signal(frame: pd.DataFrame, feature: str) -> np.ndarray:
    x = pd.to_numeric(frame[feature], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    q = float(np.nanpercentile(np.abs(x), 80))
    if q <= 0.0:
        return np.zeros(len(frame), dtype=int)

    if feature == "spread_dynamics_real":
        # Spread widening tends to mean-revert at very short horizons.
        sig = np.where(x > q, -1, np.where(x < -q, 1, 0))
    else:
        sig = np.where(x > q, 1, np.where(x < -q, -1, 0))
    return sig.astype(int)


def _trade_returns(frame: pd.DataFrame, signal: np.ndarray, horizon_ms: int, fee_bps: float) -> np.ndarray:
    px = frame["mid"].to_numpy(dtype=float)
    spread = pd.to_numeric(frame["spread_bps"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    ts_ms = (frame["ts"].astype("int64") // 1_000_000).to_numpy(dtype=np.int64)

    out: list[float] = []
    j = 0
    for i in range(len(frame)):
        s = int(signal[i])
        if s == 0:
            continue
        target = int(ts_ms[i] + horizon_ms)
        while j < len(frame) and ts_ms[j] < target:
            j += 1
        if j >= len(frame):
            break
        raw = (px[j] / (px[i] + 1e-12)) - 1.0
        # Cost includes fee + half spread crossing in bps.
        cost = (float(fee_bps) + max(0.0, float(spread[i])) * 0.5) / 10000.0
        out.append((raw * s) - cost)
    return np.asarray(out, dtype=float)


def _evaluate_feature(frame: pd.DataFrame, feature: str, horizons_ms: list[int], min_samples: int) -> dict:
    sig = _feature_signal(frame, feature)
    if sig.size == 0:
        return {"feature": feature, "best": None, "all": []}

    split = int(len(frame) * 0.7)
    train = frame.iloc[:split].copy()
    test = frame.iloc[split:].copy()
    sig_train = sig[:split]
    sig_test = sig[split:]

    all_rows: list[dict] = []
    best_row: dict | None = None
    best_score = -1e9

    for h in horizons_ms:
        r_train = _trade_returns(train, sig_train, h, fee_bps=0.8)
        r_test = _trade_returns(test, sig_test, h, fee_bps=0.8)

        m_train = _metrics(r_train)
        m_test = _metrics(r_test)

        row = {
            "horizon_ms": int(h),
            "train": asdict(m_train),
            "test": asdict(m_test),
            "passes": bool(
                m_train.samples >= min_samples
                and m_test.samples >= min_samples
                and m_train.t_stat > 2.0
                and m_train.sharpe > 1.5
                and m_test.t_stat > 2.0
                and m_test.sharpe > 1.5
            ),
        }
        all_rows.append(row)

        score = float(m_test.t_stat + 0.4 * m_test.sharpe)
        if score > best_score:
            best_score = score
            best_row = row

    return {"feature": feature, "best": best_row, "all": all_rows}


def main() -> None:
    parser = argparse.ArgumentParser(description="HF microstructure-only edge test (tick trades + true orderbook updates)")
    parser.add_argument("--microstructure-root", default="data/microstructure")
    parser.add_argument("--output", default="data/hf_microstructure_only_report.json")
    parser.add_argument("--min-samples", type=int, default=80)
    args = parser.parse_args()

    root = Path(args.microstructure_root)
    trades = _read_parquet_tree(root / "trades")
    books = _read_parquet_tree(root / "orderbook")

    if trades.empty or books.empty:
        report = {
            "status": "FAILURE",
            "reason": "missing_tick_or_orderbook_data",
            "conclusion": "cannot_test_efficiency_without_true_microstructure_streams",
        }
    else:
        frame = _normalize_inputs(trades, books)
        if frame.empty:
            report = {
                "status": "FAILURE",
                "reason": "no_overlap_after_alignment",
                "conclusion": "cannot_test_efficiency_without_synchronized_streams",
            }
        else:
            results = []
            for feature in ["ofi_real", "queue_imbalance_real", "spread_dynamics_real"]:
                results.append(_evaluate_feature(frame, feature, horizons_ms=[1000, 5000, 30000], min_samples=int(args.min_samples)))

            passing = []
            for r in results:
                for row in r["all"]:
                    if bool(row.get("passes", False)):
                        passing.append({"feature": r["feature"], **row})

            report = {
                "status": "SUCCESS" if passing else "FAILURE",
                "reason": "hf_alpha_detected" if passing else "no_hf_edge_passing_gate",
                "data_stats": {
                    "trade_rows": int(len(trades)),
                    "orderbook_rows": int(len(books)),
                    "aligned_rows_100ms": int(len(frame)),
                },
                "validation_gate": {
                    "t_stat_gt": 2.0,
                    "sharpe_gt": 1.5,
                    "horizons_ms": [1000, 5000, 30000],
                },
                "passing_edges": passing,
                "feature_results": results,
                "conclusion": (
                    "alpha_exists_at_hf_microstructure_resolution" if passing else "market_efficiency_at_tested_hf_resolution"
                ),
            }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=== HF MICROSTRUCTURE TEST ===")
    print(
        json.dumps(
            {
                "status": report.get("status"),
                "reason": report.get("reason"),
                "conclusion": report.get("conclusion"),
                "passing_edges": report.get("passing_edges", []),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
