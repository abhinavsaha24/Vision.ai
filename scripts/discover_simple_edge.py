from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import yfinance as yf

ANNUALIZATION_1H = float(np.sqrt(24 * 365))


@dataclass
class EvalMetrics:
    trades: int
    mean_return: float
    t_stat: float
    sharpe: float
    profit_factor: float
    max_drawdown: float
    win_rate: float


@dataclass
class FeatureCandidate:
    feature: str
    params: dict
    metrics: EvalMetrics
    consistency_pass: bool


@dataclass
class FinalStrategy:
    features: list[str]
    feature_params: dict


def _fetch(symbol: str, period: str, interval: str) -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval=interval, auto_adjust=False)
    if df is None or df.empty:
        raise RuntimeError("No market data downloaded")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]).lower() for c in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]
    out = df[["open", "high", "low", "close", "volume"]].copy().dropna().sort_index()
    return out


def _feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x["ret1"] = x["close"].pct_change()
    x["ret2"] = x["close"].pct_change(2)
    x["ret3"] = x["close"].pct_change(3)

    tr_a = (x["high"] - x["low"]).abs()
    tr_b = (x["high"] - x["close"].shift(1)).abs()
    tr_c = (x["low"] - x["close"].shift(1)).abs()
    x["tr"] = np.maximum(np.maximum(tr_a, tr_b), tr_c)
    x["atr_14"] = x["tr"].rolling(14, min_periods=7).mean()

    short_vol = x["ret1"].rolling(12, min_periods=6).std()
    long_vol = x["ret1"].rolling(72, min_periods=24).std()
    x["vol_expansion_ratio"] = (short_vol / (long_vol + 1e-12)).replace([np.inf, -np.inf], np.nan)

    vol_base = x["volume"].rolling(48, min_periods=16).mean()
    x["volume_spike_ratio"] = (x["volume"] / (vol_base + 1e-12)).replace([np.inf, -np.inf], np.nan)

    x["price_acceleration"] = x["ret1"].diff().fillna(0.0)

    range_short = (x["high"].rolling(12, min_periods=6).max() - x["low"].rolling(12, min_periods=6).min()).replace(0.0, np.nan)
    range_long = (x["high"].rolling(72, min_periods=24).max() - x["low"].rolling(72, min_periods=24).min()).replace(0.0, np.nan)
    x["range_compression_ratio"] = (range_short / range_long).replace([np.inf, -np.inf], np.nan)

    signed_volume = np.sign(x["close"] - x["open"]) * x["volume"]
    signed_base = x["volume"].rolling(48, min_periods=16).sum().replace(0.0, np.nan)
    x["ofi_proxy"] = (signed_volume.rolling(6, min_periods=3).sum() / (signed_base + 1e-12)).fillna(0.0)

    prior_low = x["low"].rolling(24, min_periods=12).min().shift(1)
    prior_high = x["high"].rolling(24, min_periods=12).max().shift(1)
    x["sweep_down"] = ((x["low"] < prior_low) & (x["close"] > prior_low)).astype(int)
    x["sweep_up"] = ((x["high"] > prior_high) & (x["close"] < prior_high)).astype(int)

    sr_low = x["low"].rolling(72, min_periods=24).min().shift(1)
    sr_high = x["high"].rolling(72, min_periods=24).max().shift(1)
    dist_support = ((x["close"] - sr_low).abs() / (x["close"] + 1e-12)).replace([np.inf, -np.inf], np.nan)
    dist_resist = ((sr_high - x["close"]).abs() / (x["close"] + 1e-12)).replace([np.inf, -np.inf], np.nan)
    x["near_support"] = (dist_support < 0.006).astype(int)
    x["near_resistance"] = (dist_resist < 0.006).astype(int)

    vol_sigma = long_vol.fillna(long_vol.median())
    x["panic_zone"] = ((x["ret1"] < (-2.2 * vol_sigma)) & (x["volume_spike_ratio"] > 1.7)).astype(int)

    ema_fast = x["close"].ewm(span=12, adjust=False).mean()
    ema_slow = x["close"].ewm(span=36, adjust=False).mean()
    drift = ((x["close"] - ema_slow) / (x["atr_14"] + 1e-12)).replace([np.inf, -np.inf], np.nan)
    x["trend_exhaustion"] = ((drift.abs() > 2.3) & (x["price_acceleration"] * x["ret1"] < 0.0)).astype(int)

    x["regime_shift_up"] = ((ema_fast > ema_slow) & (ema_fast.shift(1) <= ema_slow.shift(1))).astype(int)
    x["regime_shift_down"] = ((ema_fast < ema_slow) & (ema_fast.shift(1) >= ema_slow.shift(1))).astype(int)

    z_ret = ((x["ret1"] - x["ret1"].rolling(96, min_periods=32).mean()) / (x["ret1"].rolling(96, min_periods=32).std() + 1e-12)).replace([np.inf, -np.inf], np.nan)
    x["extreme_reversion"] = z_ret.fillna(0.0)

    x = x.dropna(subset=["ret1", "vol_expansion_ratio", "volume_spike_ratio", "range_compression_ratio", "atr_14"]).copy()
    return x


def _trade_returns(x: pd.DataFrame, signal: np.ndarray, horizon: int, fee_bps: float = 6.0, slip_bps: float = 4.0) -> np.ndarray:
    px = x["close"].to_numpy(dtype=float)
    cost = (fee_bps + slip_bps) / 10000.0
    out: list[float] = []
    for i in range(len(px) - horizon):
        s = int(signal[i])
        if s == 0:
            continue
        raw = (px[i + horizon] / (px[i] + 1e-12)) - 1.0
        out.append((raw * s) - cost)
    return np.asarray(out, dtype=float)


def _metrics(trades: np.ndarray) -> EvalMetrics:
    if trades.size == 0:
        return EvalMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    mu = float(np.mean(trades))
    sd = float(np.std(trades))
    t_stat = float((mu / (sd / np.sqrt(trades.size))) if sd > 1e-12 else 0.0)
    sharpe = float((mu / sd) * ANNUALIZATION_1H) if sd > 1e-12 else 0.0
    wins = trades[trades > 0]
    losses = trades[trades < 0]
    pf = float(wins.sum() / abs(losses.sum())) if losses.size else 10.0
    eq = np.cumprod(1.0 + trades)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / (peak + 1e-12)
    max_dd = float(abs(dd.min())) if dd.size else 0.0
    win_rate = float((trades > 0).mean())
    return EvalMetrics(int(trades.size), mu, t_stat, sharpe, pf, max_dd, win_rate)


def _period_consistency(x: pd.DataFrame, signal: np.ndarray, horizon: int, n_periods: int = 3) -> tuple[bool, list[dict]]:
    n = len(x)
    block = n // n_periods
    period_rows: list[dict] = []
    ok = True
    for i in range(n_periods):
        st = i * block
        ed = (i + 1) * block if i < (n_periods - 1) else n
        x_p = x.iloc[st:ed]
        s_p = signal[st:ed]
        tr = _trade_returns(x_p, s_p, horizon)
        m = _metrics(tr)
        row = {"period": i + 1, **asdict(m)}
        period_rows.append(row)
        if m.trades < 25 or m.t_stat <= 0.0 or m.sharpe <= 0.0:
            ok = False
    return ok, period_rows


def _feature_generators() -> dict[str, tuple[list[dict], Callable[[pd.DataFrame, dict], np.ndarray], int]]:
    def ofi_signal(x: pd.DataFrame, p: dict) -> np.ndarray:
        z = x["ofi_proxy"].to_numpy(dtype=float)
        v = x["vol_expansion_ratio"].to_numpy(dtype=float)
        sig = np.zeros(len(x), dtype=int)
        sig[(z > p["ofi_long"]) & (v > p["vol_floor"]) & (x["near_support"].to_numpy(dtype=int) == 1)] = 1
        sig[(z < -p["ofi_short"]) & (v > p["vol_floor"]) & (x["near_resistance"].to_numpy(dtype=int) == 1)] = -1
        return sig

    def sweep_signal(x: pd.DataFrame, p: dict) -> np.ndarray:
        vs = x["volume_spike_ratio"].to_numpy(dtype=float)
        sig = np.zeros(len(x), dtype=int)
        sig[(x["sweep_down"].to_numpy(dtype=int) == 1) & (vs > p["vol_spike"]) ] = 1
        sig[(x["sweep_up"].to_numpy(dtype=int) == 1) & (vs > p["vol_spike"]) ] = -1
        return sig

    def compression_breakout_signal(x: pd.DataFrame, p: dict) -> np.ndarray:
        comp = x["range_compression_ratio"].to_numpy(dtype=float)
        volx = x["vol_expansion_ratio"].to_numpy(dtype=float)
        h_prev = x["high"].rolling(18, min_periods=9).max().shift(1).to_numpy(dtype=float)
        l_prev = x["low"].rolling(18, min_periods=9).min().shift(1).to_numpy(dtype=float)
        c = x["close"].to_numpy(dtype=float)
        sig = np.zeros(len(x), dtype=int)
        sig[(comp < p["compression_max"]) & (volx > p["expansion_min"]) & (c > h_prev)] = 1
        sig[(comp < p["compression_max"]) & (volx > p["expansion_min"]) & (c < l_prev)] = -1
        return sig

    def panic_rebound_signal(x: pd.DataFrame, p: dict) -> np.ndarray:
        ret = x["ret1"].to_numpy(dtype=float)
        volx = x["volume_spike_ratio"].to_numpy(dtype=float)
        panic = x["panic_zone"].to_numpy(dtype=int)
        sig = np.zeros(len(x), dtype=int)
        sig[(panic == 1) & (ret < -p["drop_floor"]) & (volx > p["vol_spike"]) ] = 1
        return sig

    def exhaustion_reversion_signal(x: pd.DataFrame, p: dict) -> np.ndarray:
        ex = x["trend_exhaustion"].to_numpy(dtype=int)
        ret = x["ret1"].to_numpy(dtype=float)
        sig = np.zeros(len(x), dtype=int)
        sig[(ex == 1) & (ret > p["up_move_floor"]) ] = -1
        sig[(ex == 1) & (ret < -p["down_move_floor"]) ] = 1
        return sig

    def extreme_reversion_signal(x: pd.DataFrame, p: dict) -> np.ndarray:
        z = x["extreme_reversion"].to_numpy(dtype=float)
        reg_up = x["regime_shift_up"].to_numpy(dtype=int)
        reg_down = x["regime_shift_down"].to_numpy(dtype=int)
        sig = np.zeros(len(x), dtype=int)
        sig[(z < -p["z_floor"]) & (reg_up == 1)] = 1
        sig[(z > p["z_floor"]) & (reg_down == 1)] = -1
        return sig

    return {
        "micro_ofi_near_sr": (
            [
                {"ofi_long": 0.003, "ofi_short": 0.003, "vol_floor": 1.0},
                {"ofi_long": 0.004, "ofi_short": 0.004, "vol_floor": 1.1},
                {"ofi_long": 0.005, "ofi_short": 0.005, "vol_floor": 1.2},
            ],
            ofi_signal,
            4,
        ),
        "micro_liquidity_sweep": (
            [
                {"vol_spike": 1.2},
                {"vol_spike": 1.4},
                {"vol_spike": 1.6},
            ],
            sweep_signal,
            5,
        ),
        "behavior_compression_breakout": (
            [
                {"compression_max": 0.45, "expansion_min": 1.1},
                {"compression_max": 0.40, "expansion_min": 1.2},
                {"compression_max": 0.35, "expansion_min": 1.3},
            ],
            compression_breakout_signal,
            6,
        ),
        "behavior_panic_rebound": (
            [
                {"drop_floor": 0.010, "vol_spike": 1.6},
                {"drop_floor": 0.012, "vol_spike": 1.8},
                {"drop_floor": 0.014, "vol_spike": 2.0},
            ],
            panic_rebound_signal,
            4,
        ),
        "behavior_trend_exhaustion": (
            [
                {"up_move_floor": 0.005, "down_move_floor": 0.005},
                {"up_move_floor": 0.007, "down_move_floor": 0.007},
                {"up_move_floor": 0.009, "down_move_floor": 0.009},
            ],
            exhaustion_reversion_signal,
            4,
        ),
        "struct_regime_extreme_reversion": (
            [
                {"z_floor": 1.8},
                {"z_floor": 2.0},
                {"z_floor": 2.2},
            ],
            extreme_reversion_signal,
            5,
        ),
    }


def _discover_feature_edges(x: pd.DataFrame) -> tuple[list[FeatureCandidate], list[dict]]:
    strong: list[FeatureCandidate] = []
    audit: list[dict] = []
    gens = _feature_generators()

    for fname, (param_grid, signal_fn, horizon) in gens.items():
        best: FeatureCandidate | None = None
        for params in param_grid:
            sig = signal_fn(x, params)
            tr = _trade_returns(x, sig, horizon)
            m = _metrics(tr)
            consistent, period_rows = _period_consistency(x, sig, horizon, n_periods=3)
            passed = (m.trades > 80) and (m.t_stat > 2.0) and (m.sharpe > 1.0) and consistent
            audit.append(
                {
                    "feature": fname,
                    "params": params,
                    "horizon": horizon,
                    "metrics": asdict(m),
                    "consistency_pass": consistent,
                    "periods": period_rows,
                    "passes_single_feature_gate": passed,
                }
            )
            candidate = FeatureCandidate(feature=fname, params={**params, "horizon": horizon}, metrics=m, consistency_pass=consistent)
            if best is None:
                best = candidate
                continue
            best_score = best.metrics.t_stat + (0.3 * best.metrics.sharpe)
            cand_score = m.t_stat + (0.3 * m.sharpe)
            if cand_score > best_score:
                best = candidate

        if best is None:
            continue
        if (best.metrics.trades > 80) and (best.metrics.t_stat > 2.0) and (best.metrics.sharpe > 1.0) and best.consistency_pass:
            strong.append(best)

    strong = sorted(strong, key=lambda c: c.metrics.t_stat + (0.3 * c.metrics.sharpe), reverse=True)
    return strong, audit


def _signal_for_feature(x: pd.DataFrame, feature_name: str, params: dict) -> np.ndarray:
    param_grid, signal_fn, _h = _feature_generators()[feature_name]
    _ = param_grid
    return signal_fn(x, params)


def _build_minimal_strategy(strong_features: list[FeatureCandidate]) -> FinalStrategy | None:
    if not strong_features:
        return None
    selected = strong_features[: min(3, len(strong_features))]
    return FinalStrategy(
        features=[s.feature for s in selected],
        feature_params={s.feature: s.params for s in selected},
    )


def _strategy_signal(x: pd.DataFrame, strategy: FinalStrategy) -> tuple[np.ndarray, int]:
    signals = []
    horizons = []
    for feat in strategy.features:
        params = strategy.feature_params[feat]
        horizons.append(int(params["horizon"]))
        signals.append(_signal_for_feature(x, feat, params))
    if not signals:
        return np.zeros(len(x), dtype=int), 4

    stacked = np.vstack(signals)
    score = stacked.sum(axis=0)
    agg = np.where(score >= 1, 1, np.where(score <= -1, -1, 0))
    horizon = int(round(float(np.mean(horizons)))) if horizons else 4
    return agg.astype(int), max(2, horizon)


def _evaluate_strategy(x: pd.DataFrame, strategy: FinalStrategy) -> tuple[EvalMetrics, dict, np.ndarray, int]:
    sig, horizon = _strategy_signal(x, strategy)
    tr = _trade_returns(x, sig, horizon)
    m = _metrics(tr)
    consistent, period_rows = _period_consistency(x, sig, horizon, n_periods=3)
    return m, {"consistency_pass": consistent, "periods": period_rows}, tr, horizon


def _walk_forward(x: pd.DataFrame, strategy: FinalStrategy, windows: int = 6) -> dict:
    n = len(x)
    chunk = n // windows
    rows = []
    combined: list[np.ndarray] = []

    for i in range(1, windows):
        st = i * chunk
        ed = min((i + 1) * chunk, n)
        if ed - st < 120:
            continue
        xw = x.iloc[st:ed]
        m, consistency, tr, horizon = _evaluate_strategy(xw, strategy)
        rows.append({"window": i, "horizon": horizon, **asdict(m), **consistency})
        if tr.size:
            combined.append(tr)

    if not rows:
        return {"error": "insufficient_data"}

    merged = np.concatenate(combined) if combined else np.asarray([], dtype=float)
    return {
        "windows": len(rows),
        "detail": rows,
        "aggregate": asdict(_metrics(merged)),
    }


def _monte_carlo(trades: np.ndarray, n_paths: int = 3000) -> dict:
    if trades.size < 30:
        return {"error": "insufficient_returns"}
    finals = []
    mdds = []
    sharpes = []
    for _ in range(n_paths):
        sim = np.random.choice(trades, size=trades.size, replace=True)
        eq = np.cumprod(1.0 + sim)
        finals.append(float(eq[-1] - 1.0))
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak) / (peak + 1e-12)
        mdds.append(float(dd.min()))
        sd = float(np.std(sim))
        sharpes.append(float((np.mean(sim) / sd) * ANNUALIZATION_1H) if sd > 1e-12 else 0.0)

    f = np.asarray(finals)
    d = np.asarray(mdds)
    s = np.asarray(sharpes)
    return {
        "n_paths": n_paths,
        "median_return": float(np.median(f)),
        "p05_return": float(np.percentile(f, 5)),
        "p95_return": float(np.percentile(f, 95)),
        "probability_of_ruin": float(np.mean(f <= -0.5)),
        "tail_drawdown_p95": float(np.percentile(d, 95)),
        "sharpe_median": float(np.median(s)),
    }


def _gate_final(test_metrics: EvalMetrics) -> bool:
    return (
        (test_metrics.sharpe > 1.5)
        and (test_metrics.profit_factor > 1.5)
        and (test_metrics.max_drawdown < 0.10)
        and (test_metrics.trades > 100)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTC-USD")
    parser.add_argument("--period", default="730d")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--output", default="data/non_obvious_edge_report.json")
    args = parser.parse_args()

    raw = _fetch(args.symbol, args.period, args.interval)
    split = int(len(raw) * 0.65)
    x_train = _feature_frame(raw.iloc[:split].copy())
    x_test = _feature_frame(raw.iloc[split:].copy())

    strong_features, feature_audit = _discover_feature_edges(x_train)
    strategy = _build_minimal_strategy(strong_features)

    if strategy is None:
        report = {
            "status": "FAILURE",
            "reason": "no_single_feature_passed_individual_statistical_gate",
            "feature_validation_gate": {
                "t_stat_gt": 2.0,
                "sharpe_gt": 1.0,
                "consistency": "all_periods_positive_t_and_sharpe",
            },
            "feature_audit": feature_audit,
            "selected_features": [],
        }
    else:
        train_metrics, train_consistency, train_trades, train_h = _evaluate_strategy(x_train, strategy)
        test_metrics, test_consistency, test_trades, test_h = _evaluate_strategy(x_test, strategy)

        full_x = _feature_frame(raw.copy())
        walk_forward = _walk_forward(full_x, strategy, windows=6)
        mc = _monte_carlo(test_trades if test_trades.size else train_trades)

        final_pass = _gate_final(test_metrics)

        report = {
            "status": "SUCCESS" if final_pass else "FAILURE",
            "reason": "targets_met" if final_pass else "targets_not_met",
            "selected_features": strategy.features,
            "feature_params": strategy.feature_params,
            "train": {
                "horizon": train_h,
                "metrics": asdict(train_metrics),
                "consistency": train_consistency,
            },
            "test": {
                "horizon": test_h,
                "metrics": asdict(test_metrics),
                "consistency": test_consistency,
            },
            "walk_forward": walk_forward,
            "monte_carlo": mc,
            "feature_validation_gate": {
                "t_stat_gt": 2.0,
                "sharpe_gt": 1.0,
                "consistency": "all_periods_positive_t_and_sharpe",
            },
            "strategy_targets": {
                "sharpe_gt": 1.5,
                "profit_factor_gt": 1.5,
                "max_drawdown_lt": 0.10,
                "trades_gt": 100,
            },
            "feature_audit_top": sorted(
                feature_audit,
                key=lambda r: (float(r["metrics"]["t_stat"]) + (0.3 * float(r["metrics"]["sharpe"]))),
                reverse=True,
            )[:20],
        }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=== NON-OBVIOUS EDGE REPORT ===")
    print(
        json.dumps(
            {
                "status": report.get("status"),
                "reason": report.get("reason"),
                "selected_features": report.get("selected_features", []),
                "test_metrics": report.get("test", {}).get("metrics", {}),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
