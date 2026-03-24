from __future__ import annotations

import numpy as np
import pandas as pd


class FlowFeatureEngineer:
    """Flow-feature normalization and stable microstructure transforms."""

    @staticmethod
    def _zscore(series: pd.Series, window: int, cap: float = 4.0) -> pd.Series:
        mean = series.rolling(window).mean()
        std = series.rolling(window).std().replace(0.0, np.nan)
        z = ((series - mean) / std).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        return z.clip(-cap, cap)

    @staticmethod
    def enrich(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()

        for col, default in (
            ("open_interest", 0.0),
            ("funding_rate", 0.0),
            ("liquidation_long_usd", 0.0),
            ("liquidation_short_usd", 0.0),
        ):
            if col not in out.columns:
                out[col] = default
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(default)

        out["oi_delta"] = out["open_interest"].pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
        out["oi_delta_z"] = FlowFeatureEngineer._zscore(out["oi_delta"], window=72)

        out["funding_bias"] = np.tanh(out["funding_rate"] * 2000.0)
        out["funding_z"] = FlowFeatureEngineer._zscore(out["funding_rate"], window=96)

        out["liq_total"] = out["liquidation_long_usd"] + out["liquidation_short_usd"]
        denom = out["liq_total"].replace(0.0, np.nan)
        out["liquidation_imbalance"] = (
            (out["liquidation_short_usd"] - out["liquidation_long_usd"]) / denom
        ).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        out["liquidation_z"] = FlowFeatureEngineer._zscore(out["liq_total"], window=72)

        if "close" not in out.columns:
            raise ValueError("flow_features_missing_required_column:close")
        close = pd.to_numeric(out["close"], errors="coerce")
        close = close.ffill().bfill()
        if close.isna().all():
            close = pd.Series(0.0, index=out.index)
        else:
            close = close.fillna(float(close.dropna().iloc[-1]))
        ret1 = close.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
        vol = ret1.rolling(24).std().replace(0.0, np.nan)
        out["volatility_24"] = vol.fillna(vol.median() if not vol.dropna().empty else 0.0)

        trend_strength = (
            (close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()).abs()
            / close.replace(0.0, np.nan)
        ).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        out["trend_strength"] = trend_strength

        oi_delta = out["oi_delta"].fillna(0.0)
        price_stall = ret1.abs().rolling(8).mean().fillna(0.0) < ret1.abs().rolling(48).median().fillna(0.0)
        funding_extreme = out["funding_z"].abs() > 1.4
        not_trending = trend_strength < 0.003

        # Behavioral flow structures replace brittle raw threshold logic.
        out["flow_funding_divergence"] = (funding_extreme & not_trending).astype(float)
        out["flow_oi_trap"] = ((out["oi_delta_z"] > 1.0) & price_stall).astype(float)
        out["flow_liquidation_reversal"] = (
            (out["liquidation_z"] > 1.2) & (out["liquidation_z"].diff(2).fillna(0.0) < -0.2)
        ).astype(float)

        flow_vector = (
            (out["funding_z"] * -0.35)
            + (out["oi_delta_z"] * -0.30)
            + (out["liquidation_imbalance"] * 0.35)
        )
        vol_adj = out["volatility_24"].replace(0.0, np.nan)
        out["flow_behavior_score"] = (flow_vector / vol_adj).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        out["flow_behavior_score_z"] = FlowFeatureEngineer._zscore(out["flow_behavior_score"], window=72)

        return out.fillna(0.0)


def merge_flow_into_bars(bars: pd.DataFrame, flow: pd.DataFrame) -> pd.DataFrame:
    base = bars.copy().sort_index()
    base_idx = pd.DatetimeIndex(pd.to_datetime(base.index))
    if base_idx.tz is None:
        base_idx = base_idx.tz_localize("UTC")
    else:
        base_idx = base_idx.tz_convert("UTC")
    base.index = base_idx

    flow_df = flow.copy().sort_index()
    flow_idx = pd.DatetimeIndex(pd.to_datetime(flow_df.index))
    if flow_idx.tz is None:
        flow_idx = flow_idx.tz_localize("UTC")
    else:
        flow_idx = flow_idx.tz_convert("UTC")
    flow_df.index = flow_idx

    merged = base.join(flow_df, how="left")
    merged = merged.ffill().fillna(0.0)
    return FlowFeatureEngineer.enrich(merged)
