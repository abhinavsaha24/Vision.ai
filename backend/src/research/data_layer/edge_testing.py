from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .schema import UnivariateThresholds

ANNUALIZATION_1H = float(np.sqrt(24 * 365))


@dataclass
class UniMetrics:
    observations: int
    mean_return: float
    t_stat: float
    sharpe: float
    win_rate: float


def run_univariate_tests(feature_table: pd.DataFrame, thresholds: UnivariateThresholds) -> dict:
    if feature_table.empty:
        return {"status": "FAILURE", "reason": "empty_feature_table", "results": []}

    df = feature_table.copy().sort_values("ts").reset_index(drop=True)
    y_col = df["target_return_3h"] if "target_return_3h" in df.columns else pd.Series(0.0, index=df.index)
    y = pd.to_numeric(y_col, errors="coerce").fillna(0.0).to_numpy(dtype=float)

    candidate_features = [
        "ofi",
        "aggressor_imbalance",
        "depth_imbalance",
        "liquidity_vacuum",
        "spread_expansion",
        "oi_change",
        "funding_rate",
        "basis",
        "funding_crowding",
        "oi_divergence",
        "liquidation_pressure",
        "liquidation_count",
        "volatility_shock_z",
        "volatility_shock_flag",
    ]

    out = []
    for feat in candidate_features:
        if feat not in df.columns:
            continue
        x = pd.to_numeric(df[feat], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        signal = np.where(x > np.nanpercentile(x, 70), 1, np.where(x < np.nanpercentile(x, 30), -1, 0))
        rets = (signal * y)
        rets = rets[signal != 0]
        m = _metrics(rets)
        consistent, periods = _period_stability(rets)
        passed = (
            m.observations >= thresholds.min_trades
            and m.t_stat > thresholds.min_t_stat
            and m.sharpe > thresholds.min_sharpe
            and consistent
        )
        out.append(
            {
                "feature": feat,
                "metrics": asdict(m),
                "period_consistency": consistent,
                "periods": periods,
                "passes_gate": passed,
            }
        )

    out = sorted(out, key=lambda r: (float(r["metrics"]["t_stat"]) + 0.25 * float(r["metrics"]["sharpe"])), reverse=True)
    passing = [r for r in out if r["passes_gate"]]
    return {
        "status": "PASS" if passing else "FAIL",
        "thresholds": asdict(thresholds),
        "passing_features": passing,
        "top_results": out[:20],
    }


def _metrics(rets: np.ndarray) -> UniMetrics:
    if rets.size == 0:
        return UniMetrics(0, 0.0, 0.0, 0.0, 0.0)
    mu = float(np.mean(rets))
    sd = float(np.std(rets))
    t_stat = float((mu / (sd / np.sqrt(rets.size))) if sd > 1e-12 else 0.0)
    sharpe = float((mu / sd) * ANNUALIZATION_1H) if sd > 1e-12 else 0.0
    win_rate = float((rets > 0).mean())
    return UniMetrics(observations=int(rets.size), mean_return=mu, t_stat=t_stat, sharpe=sharpe, win_rate=win_rate)


def _period_stability(rets: np.ndarray, n_periods: int = 3) -> tuple[bool, list[dict]]:
    if rets.size < n_periods * 10:
        return False, []
    chunk = rets.size // n_periods
    rows = []
    ok = True
    for i in range(n_periods):
        st = i * chunk
        ed = (i + 1) * chunk if i < (n_periods - 1) else rets.size
        seg = rets[st:ed]
        m = _metrics(seg)
        rows.append({"period": i + 1, **asdict(m)})
        if m.observations < 10 or m.t_stat <= 0.0 or m.sharpe <= 0.0:
            ok = False
    return ok, rows
