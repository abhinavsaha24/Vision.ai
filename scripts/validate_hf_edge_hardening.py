from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class PerfMetrics:
    samples: int
    expectancy: float
    t_stat: float
    sharpe: float
    profit_factor: float
    max_drawdown: float
    win_rate: float


def _read_parquet_tree(root: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for fp in sorted(root.rglob("*.parquet")):
        try:
            df = pd.read_parquet(fp)
        except Exception:
            continue
        if df is not None and not df.empty:
            frames.append(df)
    return pd.concat(frames, axis=0, ignore_index=True) if frames else pd.DataFrame()


def _session_label(ts: pd.Series) -> pd.Series:
    h = pd.to_datetime(ts, utc=True).dt.hour
    return pd.Series(np.where(h < 8, "asia", np.where(h < 16, "eu", "us")), index=ts.index)


def _metrics(x: np.ndarray) -> PerfMetrics:
    if x.size == 0:
        return PerfMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    mu = float(np.mean(x))
    sd = float(np.std(x))
    t = float((mu / (sd / np.sqrt(x.size))) if sd > 1e-12 else 0.0)
    sharpe = float((mu / sd) * np.sqrt(max(1.0, float(x.size)))) if sd > 1e-12 else 0.0
    wins = x[x > 0.0]
    losses = x[x < 0.0]
    pf = float(wins.sum() / abs(losses.sum())) if losses.size > 0 else 10.0
    eq = np.cumprod(1.0 + x)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / (peak + 1e-12)
    mdd = float(abs(dd.min())) if dd.size else 0.0
    wr = float((x > 0.0).mean())
    return PerfMetrics(int(x.size), mu, t, sharpe, pf, mdd, wr)


def _prepare_frame(trades: pd.DataFrame, books: pd.DataFrame) -> pd.DataFrame:
    t = trades.copy()
    b = books.copy()

    t["ts"] = pd.to_datetime(t["exchange_ts_ms"], unit="ms", utc=True, errors="coerce")
    b["ts"] = pd.to_datetime(b["exchange_ts_ms"], unit="ms", utc=True, errors="coerce")
    t = t.dropna(subset=["ts"])
    b = b.dropna(subset=["ts"])

    t["signed_qty"] = np.where(
        t["side"].astype(str).str.lower().eq("buy"),
        pd.to_numeric(t["quantity"], errors="coerce").fillna(0.0),
        -pd.to_numeric(t["quantity"], errors="coerce").fillna(0.0),
    )

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
            spread_bps=("spread_bps", "last"),
            queue_imbalance=("orderbook_imbalance", "last"),
            bid_depth=("bid_depth_top_n", "last"),
            ask_depth=("ask_depth_top_n", "last"),
        )
        .reset_index()
    )

    parts: list[pd.DataFrame] = []
    keys = sorted(set(zip(b_bar["venue"], b_bar["symbol"])))
    for venue, symbol in keys:
        tb = t_bar[(t_bar["venue"] == venue) & (t_bar["symbol"] == symbol)].sort_values("ts")
        bb = b_bar[(b_bar["venue"] == venue) & (b_bar["symbol"] == symbol)].sort_values("ts")
        if tb.empty or bb.empty:
            continue
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

    m["mid"] = pd.to_numeric(m["mid_price"], errors="coerce")
    m["spread_bps"] = pd.to_numeric(m["spread_bps"], errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(0.0, 80.0)
    m["queue_imbalance"] = pd.to_numeric(m["queue_imbalance"], errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0)
    m["bid_depth"] = pd.to_numeric(m["bid_depth"], errors="coerce").fillna(0.0)
    m["ask_depth"] = pd.to_numeric(m["ask_depth"], errors="coerce").fillna(0.0)
    m["signed_flow"] = pd.to_numeric(m["signed_flow"], errors="coerce").fillna(0.0)
    m["trade_qty"] = pd.to_numeric(m["trade_qty"], errors="coerce").fillna(0.0)

    m = m[np.isfinite(m["mid"]) & (m["mid"] > 0.0)].copy()
    m = m.sort_values(["symbol", "ts"]).reset_index(drop=True)
    m["ret_100ms"] = m.groupby("symbol", dropna=False)["mid"].pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
    m = m[m["ret_100ms"].abs() <= 0.10].copy()

    m["date"] = pd.to_datetime(m["ts"], utc=True).dt.date.astype(str)
    m["session"] = _session_label(m["ts"])

    vol = m.groupby("symbol", dropna=False)["ret_100ms"].transform(lambda s: s.abs().rolling(100, min_periods=30).mean().fillna(s.abs().median()))
    q1 = vol.quantile(0.33)
    q2 = vol.quantile(0.66)
    m["regime"] = np.where(vol <= q1, "low_vol", np.where(vol <= q2, "mid_vol", "high_vol"))

    return m


def _build_signal(frame: pd.DataFrame) -> np.ndarray:
    x = frame["queue_imbalance"].to_numpy(dtype=float)
    q = float(np.nanpercentile(np.abs(x), 80))
    if q <= 0.0:
        return np.zeros(len(frame), dtype=int)
    return np.where(x > q, 1, np.where(x < -q, -1, 0)).astype(int)


def _simulate(frame: pd.DataFrame, signal: np.ndarray, horizon_ms: int, delay_ms: int, taker_fee_bps: float, maker_fee_bps: float, maker_ratio: float, slippage_coef_bps: float, base_size: float, max_exposure: float, stop_loss: float) -> np.ndarray:
    ts_ms = (pd.to_datetime(frame["ts"], utc=True).astype("int64") // 1_000_000).to_numpy(dtype=np.int64)
    mid = frame["mid"].to_numpy(dtype=float)
    spread = frame["spread_bps"].to_numpy(dtype=float)
    depth = (frame["bid_depth"].to_numpy(dtype=float) + frame["ask_depth"].to_numpy(dtype=float)).clip(min=1e-6)
    qimb = np.abs(frame["queue_imbalance"].to_numpy(dtype=float))

    out: list[float] = []
    j_entry = 0
    j_exit = 0

    for i in range(len(frame)):
        s = int(signal[i])
        if s == 0:
            continue

        strength = min(1.0, float(qimb[i]))
        pos = float(np.clip(base_size * strength, 0.0, max_exposure)) * float(s)
        if pos == 0.0:
            continue

        entry_target = int(ts_ms[i] + delay_ms)
        while j_entry < len(frame) and ts_ms[j_entry] < entry_target:
            j_entry += 1
        if j_entry >= len(frame):
            break

        exit_target = int(ts_ms[j_entry] + horizon_ms)
        while j_exit < len(frame) and ts_ms[j_exit] < exit_target:
            j_exit += 1
        if j_exit >= len(frame):
            break

        raw = (mid[j_exit] / (mid[j_entry] + 1e-12)) - 1.0

        fee_bps = maker_ratio * maker_fee_bps + (1.0 - maker_ratio) * taker_fee_bps
        spread_cross_bps = (1.0 - maker_ratio) * 0.5 * max(0.0, float(spread[j_entry]))
        slip_bps = float(slippage_coef_bps) * float(abs(pos)) * (1.0 + float(frame["trade_qty"].iloc[j_entry])) / float(depth[j_entry])
        total_cost = (fee_bps + spread_cross_bps + slip_bps) / 10000.0

        pnl = (raw * pos) - total_cost
        pnl = max(pnl, -abs(stop_loss))
        out.append(float(pnl))

    return np.asarray(out, dtype=float)


def _evaluate_segments(frame: pd.DataFrame, signal: np.ndarray, delays: list[int], horizon_ms: int, min_samples: int) -> dict:
    frame = frame.reset_index(drop=True)
    signal = np.asarray(signal, dtype=int)
    segment_defs = {
        "by_symbol": ["symbol"],
        "by_session": ["session"],
        "by_symbol_session": ["symbol", "session"],
        "by_regime": ["regime"],
    }

    delay_results: list[dict] = []
    for d in delays:
        pnl = _simulate(
            frame,
            signal,
            horizon_ms=horizon_ms,
            delay_ms=d,
            taker_fee_bps=5.0,
            maker_fee_bps=2.0,
            maker_ratio=0.25,
            slippage_coef_bps=3.0,
            base_size=0.30,
            max_exposure=1.0,
            stop_loss=0.01,
        )
        agg = _metrics(pnl)

        segment_rows: dict[str, list[dict]] = {}
        segment_pass = True
        for name, cols in segment_defs.items():
            rows = []
            for key, sub in frame.groupby(cols, dropna=False):
                sub_sig = signal[sub.index.to_numpy()]
                sub_pnl = _simulate(
                    sub.reset_index(drop=True),
                    sub_sig,
                    horizon_ms=horizon_ms,
                    delay_ms=d,
                    taker_fee_bps=5.0,
                    maker_fee_bps=2.0,
                    maker_ratio=0.25,
                    slippage_coef_bps=3.0,
                    base_size=0.30,
                    max_exposure=1.0,
                    stop_loss=0.01,
                )
                m = _metrics(sub_pnl)
                key_str = str(tuple(key)) if isinstance(key, tuple) else str(key)
                passed = bool(m.samples >= min_samples and m.t_stat > 2.0 and m.sharpe > 1.5)
                rows.append({"segment": key_str, "metrics": asdict(m), "passes": passed})
                if m.samples >= min_samples and not passed:
                    segment_pass = False
            segment_rows[name] = rows

        delay_pass = bool(
            agg.samples >= min_samples
            and agg.sharpe > 1.5
            and agg.t_stat > 2.0
            and agg.profit_factor > 1.5
            and agg.max_drawdown < 0.10
            and segment_pass
        )

        delay_results.append(
            {
                "delay_ms": int(d),
                "aggregate": asdict(agg),
                "segments": segment_rows,
                "passes": delay_pass,
            }
        )

    all_pass = bool(delay_results) and all(bool(x.get("passes", False)) for x in delay_results)
    return {"delay_results": delay_results, "all_delays_pass": all_pass}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and harden discovered HF microstructure edge before deployment")
    parser.add_argument("--microstructure-root", default="data/microstructure")
    parser.add_argument("--output", default="data/hf_edge_hardening_report.json")
    parser.add_argument("--horizon-ms", type=int, default=1000)
    parser.add_argument("--min-samples", type=int, default=80)
    args = parser.parse_args()

    root = Path(args.microstructure_root)
    trades = _read_parquet_tree(root / "trades")
    books = _read_parquet_tree(root / "orderbook")

    frame = _prepare_frame(trades, books) if (not trades.empty and not books.empty) else pd.DataFrame()

    if frame.empty:
        report = {
            "status": "REJECT",
            "reason": "insufficient_synchronized_microstructure_data",
            "final_requirements": {
                "net_sharpe_gt": 1.5,
                "profit_factor_gt": 1.5,
                "max_drawdown_lt": 0.10,
                "stable_across_datasets": True,
            },
        }
    else:
        signal = _build_signal(frame)
        unique_days = sorted(set(frame["date"].astype(str).tolist()))
        unique_symbols = sorted(set(frame["symbol"].astype(str).tolist()))
        unique_sessions = sorted(set(frame["session"].astype(str).tolist()))

        robustness = _evaluate_segments(
            frame=frame,
            signal=signal,
            delays=[50, 100, 250, 500],
            horizon_ms=int(args.horizon_ms),
            min_samples=int(args.min_samples),
        )

        multi_day_ok = len(unique_days) >= 2
        multi_symbol_ok = len(unique_symbols) >= 2
        multi_session_ok = all(s in unique_sessions for s in ["asia", "eu", "us"])

        final_pass = bool(
            multi_day_ok
            and multi_symbol_ok
            and multi_session_ok
            and bool(robustness.get("all_delays_pass", False))
        )

        reject_reasons = []
        if not multi_day_ok:
            reject_reasons.append("insufficient_day_coverage")
        if not multi_symbol_ok:
            reject_reasons.append("insufficient_symbol_coverage")
        if not multi_session_ok:
            reject_reasons.append("insufficient_session_coverage")
        if not bool(robustness.get("all_delays_pass", False)):
            reject_reasons.append("edge_fails_under_costs_or_latency_or_dataset_stability")

        report = {
            "status": "DEPLOYABLE" if final_pass else "REJECT",
            "reason": "all_hardening_checks_passed" if final_pass else ";".join(reject_reasons),
            "data_coverage": {
                "days": unique_days,
                "symbols": unique_symbols,
                "sessions": unique_sessions,
                "rows": int(len(frame)),
                "signal_nonzero": int(np.count_nonzero(signal)),
            },
            "edge": "queue_imbalance_real",
            "transaction_cost_model": {
                "taker_fee_bps": 5.0,
                "maker_fee_bps": 2.0,
                "maker_ratio": 0.25,
                "spread_crossing": "0.5*spread*(1-maker_ratio)",
                "slippage_model": "slippage_coef_bps * abs(position) * (1+trade_qty)/depth",
            },
            "latency_test_ms": [50, 100, 250, 500],
            "positioning_model": {
                "size_rule": "base_size * |queue_imbalance| clipped to max_exposure",
                "base_size": 0.30,
                "max_exposure": 1.0,
                "stop_loss_per_trade": 0.01,
            },
            "robustness": robustness,
            "final_requirements": {
                "net_sharpe_gt": 1.5,
                "profit_factor_gt": 1.5,
                "max_drawdown_lt": 0.10,
                "stable_across_datasets": True,
            },
            "rule_check": {
                "reject_if_disappears_after_costs_latency": not final_pass,
            },
        }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=== HF EDGE HARDENING REPORT ===")
    print(
        json.dumps(
            {
                "status": report.get("status"),
                "reason": report.get("reason"),
                "coverage": report.get("data_coverage", {}),
                "all_delays_pass": report.get("robustness", {}).get("all_delays_pass", False),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
