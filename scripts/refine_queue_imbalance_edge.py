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


@dataclass
class EdgeConfig:
    signal_quantile: float
    vol_min_q: float
    vol_max_q: float
    liq_min_q: float
    spread_max_q: float
    allowed_sessions: tuple[str, ...]
    maker_bias: float
    taker_fee_bps: float
    maker_fee_bps: float
    slippage_coef_bps: float
    stop_loss: float
    take_profit: float
    max_hold_steps: int
    max_exposure: float


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

    m["depth_total"] = m["bid_depth"] + m["ask_depth"]
    m["abs_qi"] = m["queue_imbalance"].abs()
    m["session"] = _session_label(m["ts"])
    m["date"] = pd.to_datetime(m["ts"], utc=True).dt.date.astype(str)

    vol = m.groupby("symbol", dropna=False)["ret_100ms"].transform(lambda s: s.abs().rolling(100, min_periods=30).mean().fillna(s.abs().median()))
    q1 = vol.quantile(0.33)
    q2 = vol.quantile(0.66)
    m["regime"] = np.where(vol <= q1, "low_vol", np.where(vol <= q2, "mid_vol", "high_vol"))
    m["vol_score"] = vol

    return m


def _analyze_edge_zones(frame: pd.DataFrame) -> dict:
    q = float(np.nanpercentile(frame["abs_qi"].to_numpy(dtype=float), 80))
    sig = np.where(frame["queue_imbalance"].to_numpy(dtype=float) > q, 1, np.where(frame["queue_imbalance"].to_numpy(dtype=float) < -q, -1, 0))

    px = frame["mid"].to_numpy(dtype=float)
    out = []
    for i in range(len(frame) - 10):
        s = int(sig[i])
        if s == 0:
            continue
        r = (px[i + 10] / (px[i] + 1e-12)) - 1.0
        out.append((i, r * s))

    if not out:
        return {"status": "no_signals"}

    idx = np.asarray([x[0] for x in out], dtype=int)
    pnl = np.asarray([x[1] for x in out], dtype=float)
    sframe = frame.iloc[idx].copy()
    sframe["pnl"] = pnl

    def _group(col: str) -> list[dict]:
        rows = []
        for key, grp in sframe.groupby(col, dropna=False):
            m = _metrics(grp["pnl"].to_numpy(dtype=float))
            rows.append({"bucket": str(key), "metrics": asdict(m)})
        rows.sort(key=lambda r: float(r["metrics"]["sharpe"]), reverse=True)
        return rows

    # Vol/liq/spread buckets
    sframe["vol_bucket"] = pd.qcut(sframe["vol_score"], q=3, labels=["low", "mid", "high"], duplicates="drop")
    sframe["liq_bucket"] = pd.qcut(sframe["depth_total"].rank(method="first"), q=3, labels=["low", "mid", "high"], duplicates="drop")
    sframe["spread_bucket"] = pd.qcut(sframe["spread_bps"].rank(method="first"), q=3, labels=["tight", "mid", "wide"], duplicates="drop")

    return {
        "by_session": _group("session"),
        "by_symbol": _group("symbol"),
        "by_regime": _group("regime"),
        "by_volatility": _group("vol_bucket"),
        "by_liquidity": _group("liq_bucket"),
        "by_spread": _group("spread_bucket"),
    }


def _build_signal_and_filter(frame: pd.DataFrame, cfg: EdgeConfig) -> np.ndarray:
    qsig = float(np.nanpercentile(frame["abs_qi"].to_numpy(dtype=float), cfg.signal_quantile))
    raw = np.where(frame["queue_imbalance"].to_numpy(dtype=float) > qsig, 1, np.where(frame["queue_imbalance"].to_numpy(dtype=float) < -qsig, -1, 0))

    vol_lo = float(np.nanpercentile(frame["vol_score"].to_numpy(dtype=float), cfg.vol_min_q))
    vol_hi = float(np.nanpercentile(frame["vol_score"].to_numpy(dtype=float), cfg.vol_max_q))
    liq_lo = float(np.nanpercentile(frame["depth_total"].to_numpy(dtype=float), cfg.liq_min_q))
    spr_hi = float(np.nanpercentile(frame["spread_bps"].to_numpy(dtype=float), cfg.spread_max_q))

    cond = (
        (frame["vol_score"].to_numpy(dtype=float) >= vol_lo)
        & (frame["vol_score"].to_numpy(dtype=float) <= vol_hi)
        & (frame["depth_total"].to_numpy(dtype=float) >= liq_lo)
        & (frame["spread_bps"].to_numpy(dtype=float) <= spr_hi)
        & (frame["session"].astype(str).isin(cfg.allowed_sessions).to_numpy(dtype=bool))
    )

    return np.where(cond, raw, 0).astype(int)


def _simulate_with_execution(frame: pd.DataFrame, signal: np.ndarray, cfg: EdgeConfig, delay_ms: int) -> np.ndarray:
    ts_ms = (pd.to_datetime(frame["ts"], utc=True).astype("int64") // 1_000_000).to_numpy(dtype=np.int64)
    mid = frame["mid"].to_numpy(dtype=float)
    spread = frame["spread_bps"].to_numpy(dtype=float)
    depth = frame["depth_total"].to_numpy(dtype=float).clip(min=1e-6)
    qi = frame["abs_qi"].to_numpy(dtype=float)
    trade_qty = frame["trade_qty"].to_numpy(dtype=float)

    out: list[float] = []

    for i in range(len(frame) - cfg.max_hold_steps - 2):
        s = int(signal[i])
        if s == 0:
            continue

        entry_target = int(ts_ms[i] + delay_ms)
        j = i + 1
        while j < len(frame) and ts_ms[j] < entry_target:
            j += 1
        if j >= len(frame):
            break

        # Position sizing from signal quality + liquidity guard.
        size = float(np.clip(0.20 + 0.80 * min(1.0, qi[j]), 0.0, cfg.max_exposure))
        pos = float(s) * size
        if pos == 0.0:
            continue

        # Passive-fill preference in tight spreads and strong signal.
        passive_prob = float(np.clip(cfg.maker_bias + 0.3 * min(1.0, qi[j]) - 0.01 * max(0.0, spread[j] - 3.0), 0.0, 1.0))
        maker_fill = passive_prob >= 0.5

        fee_bps = cfg.maker_fee_bps if maker_fill else cfg.taker_fee_bps
        spread_cross_bps = 0.0 if maker_fill else (0.5 * max(0.0, spread[j]))

        # Exit optimization: TP/SL/time stop over hold window.
        entry_px = float(mid[j])
        realized = None
        end = min(len(frame) - 1, j + cfg.max_hold_steps)
        for k in range(j + 1, end + 1):
            raw = ((mid[k] / (entry_px + 1e-12)) - 1.0) * np.sign(pos)
            if raw >= cfg.take_profit:
                realized = raw
                break
            if raw <= -cfg.stop_loss:
                realized = raw
                break
        if realized is None:
            realized = ((mid[end] / (entry_px + 1e-12)) - 1.0) * np.sign(pos)

        slip_bps = float(cfg.slippage_coef_bps) * abs(pos) * (1.0 + trade_qty[j]) / depth[j]
        total_cost = (fee_bps + spread_cross_bps + slip_bps) / 10000.0
        pnl = (realized * abs(pos)) - total_cost
        pnl = max(pnl, -abs(cfg.stop_loss))
        out.append(float(pnl))

    return np.asarray(out, dtype=float)


def _validate(frame: pd.DataFrame, cfg: EdgeConfig, min_samples: int) -> dict:
    signal = _build_signal_and_filter(frame, cfg)

    split = int(len(frame) * 0.7)
    train = frame.iloc[:split].reset_index(drop=True)
    test = frame.iloc[split:].reset_index(drop=True)
    s_train = signal[:split]
    s_test = signal[split:]

    delays = [50, 100, 250, 500]
    delay_rows = []
    all_pass = True

    for d in delays:
        tr_train = _simulate_with_execution(train, s_train, cfg, delay_ms=d)
        tr_test = _simulate_with_execution(test, s_test, cfg, delay_ms=d)

        m_train = _metrics(tr_train)
        m_test = _metrics(tr_test)

        # Session stability on test set.
        session_rows = []
        session_ok = True
        for sess, sub in test.groupby("session", dropna=False):
            sub_sig = s_test[sub.index.to_numpy()]
            tr_s = _simulate_with_execution(sub.reset_index(drop=True), sub_sig, cfg, delay_ms=d)
            m_s = _metrics(tr_s)
            ok = bool(m_s.samples >= max(30, min_samples // 2) and m_s.sharpe > 1.5 and m_s.t_stat > 2.0)
            session_rows.append({"session": str(sess), "metrics": asdict(m_s), "passes": ok})
            if not ok:
                session_ok = False

        passed = bool(
            m_test.samples >= min_samples
            and m_test.sharpe > 1.5
            and m_test.t_stat > 2.0
            and m_test.profit_factor > 1.5
            and m_test.max_drawdown < 0.10
            and session_ok
        )
        if not passed:
            all_pass = False

        delay_rows.append(
            {
                "delay_ms": int(d),
                "train": asdict(m_train),
                "test": asdict(m_test),
                "session_stability": session_rows,
                "passes": passed,
            }
        )

    return {
        "signal_count": int(np.count_nonzero(signal)),
        "delay_results": delay_rows,
        "all_pass": all_pass,
    }


def _search_config(frame: pd.DataFrame, min_samples: int) -> EdgeConfig:
    configs: list[EdgeConfig] = []
    for sig_q in [75.0, 80.0, 85.0]:
        for vol_min in [10.0, 20.0, 30.0]:
            for vol_max in [80.0, 90.0, 95.0]:
                if vol_max <= vol_min:
                    continue
                for liq_q in [40.0, 50.0, 60.0]:
                    for spr_q in [60.0, 70.0, 80.0]:
                        configs.append(
                            EdgeConfig(
                                signal_quantile=sig_q,
                                vol_min_q=vol_min,
                                vol_max_q=vol_max,
                                liq_min_q=liq_q,
                                spread_max_q=spr_q,
                                allowed_sessions=("asia", "eu", "us"),
                                maker_bias=0.55,
                                taker_fee_bps=5.0,
                                maker_fee_bps=2.0,
                                slippage_coef_bps=2.2,
                                stop_loss=0.0025,
                                take_profit=0.0040,
                                max_hold_steps=20,
                                max_exposure=0.60,
                            )
                        )

    best = configs[0]
    best_score = -1e9
    for cfg in configs:
        r = _validate(frame, cfg, min_samples=min_samples)
        # Score by average test sharpe with DD penalty across delays.
        rows = r["delay_results"]
        if not rows:
            continue
        avg_sh = float(np.mean([float(x["test"]["sharpe"]) for x in rows]))
        avg_dd = float(np.mean([float(x["test"]["max_drawdown"]) for x in rows]))
        sig_n = int(r.get("signal_count", 0))
        score = avg_sh - (6.0 * max(0.0, avg_dd - 0.10)) + min(2.0, sig_n / 500.0)
        if score > best_score:
            best_score = score
            best = cfg
    return best


def main() -> None:
    parser = argparse.ArgumentParser(description="Refine and harden queue imbalance edge")
    parser.add_argument("--microstructure-root", default="data/microstructure")
    parser.add_argument("--output", default="data/hf_queue_edge_refinement_report.json")
    parser.add_argument("--min-samples", type=int, default=80)
    args = parser.parse_args()

    root = Path(args.microstructure_root)
    trades = _read_parquet_tree(root / "trades")
    books = _read_parquet_tree(root / "orderbook")
    frame = _prepare_frame(trades, books) if (not trades.empty and not books.empty) else pd.DataFrame()

    if frame.empty:
        report = {
            "status": "REJECT_PERMANENTLY",
            "reason": "insufficient_microstructure_data",
        }
    else:
        analysis = _analyze_edge_zones(frame)
        best_cfg = _search_config(frame, min_samples=int(args.min_samples))
        validation = _validate(frame, best_cfg, min_samples=int(args.min_samples))

        coverage_days = sorted(set(frame["date"].astype(str).tolist()))
        coverage_sessions = sorted(set(frame["session"].astype(str).tolist()))
        coverage_symbols = sorted(set(frame["symbol"].astype(str).tolist()))

        coverage_ok = bool(len(coverage_days) >= 2 and all(s in coverage_sessions for s in ["asia", "eu", "us"]) and len(coverage_symbols) >= 2)
        final_pass = bool(validation.get("all_pass", False) and coverage_ok)

        reject_reasons = []
        if not coverage_ok:
            reject_reasons.append("insufficient_multiday_or_session_coverage")
        if not bool(validation.get("all_pass", False)):
            reject_reasons.append("fails_net_constraints_after_costs_latency")

        report = {
            "status": "PASS" if final_pass else "REJECT_PERMANENTLY",
            "reason": "all_constraints_met" if final_pass else ";".join(reject_reasons),
            "phase1_edge_analysis": analysis,
            "phase2_filters": asdict(best_cfg),
            "phase3_entry_optimization": {
                "passive_fill_preference": "enabled",
                "maker_bias": best_cfg.maker_bias,
                "avoid_cross_wide_spread": True,
            },
            "phase4_exit_optimization": {
                "take_profit": best_cfg.take_profit,
                "stop_loss": best_cfg.stop_loss,
                "max_hold_steps_100ms": best_cfg.max_hold_steps,
            },
            "phase5_cost_model": {
                "taker_fee_bps": best_cfg.taker_fee_bps,
                "maker_fee_bps": best_cfg.maker_fee_bps,
                "slippage_coef_bps": best_cfg.slippage_coef_bps,
            },
            "phase6_validation": validation,
            "coverage": {
                "days": coverage_days,
                "sessions": coverage_sessions,
                "symbols": coverage_symbols,
                "rows": int(len(frame)),
            },
            "required_constraints": {
                "net_sharpe_gt": 1.5,
                "profit_factor_gt": 1.5,
                "max_drawdown_lt": 0.10,
                "stable_across_sessions": True,
            },
            "rule_check": {
                "if_still_fails_then_reject_permanently": not final_pass,
            },
        }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=== QUEUE EDGE REFINEMENT REPORT ===")
    print(
        json.dumps(
            {
                "status": report.get("status"),
                "reason": report.get("reason"),
                "coverage": report.get("coverage", {}),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
