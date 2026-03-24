from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from backend.src.platform.edge_registry import EdgeRegistry
from backend.src.platform.flow_features import FlowFeatureEngineer


@dataclass
class DiscoveryConfig:
    horizons: tuple[int, ...] = (2, 4, 8, 12)
    min_event_samples: int = 200
    min_segment_samples: int = 200
    confidence_z: float = 1.96
    train_fraction: float = 0.70
    min_assets_required: int = 2
    max_top_edges: int = 100
    max_pf_sanity: float = 10.0
    min_oos_samples: int = 120
    min_total_samples: int = 200
    min_oos_t_stat: float = 2.0
    min_oos_profit_factor: float = 1.2


class EdgeDiscoveryEngine:
    def __init__(self, config: DiscoveryConfig | None = None):
        self.config = config or DiscoveryConfig()

    @staticmethod
    def _inject_cross_asset_context(symbol_frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        if not symbol_frames:
            return {}

        normalized: dict[str, pd.DataFrame] = {}
        for symbol, df in symbol_frames.items():
            frame = df.copy().sort_index()
            frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index, utc=True))
            normalized[symbol] = frame

        base_symbol = "BTC-USD" if "BTC-USD" in normalized else next(iter(normalized.keys()))
        eth_symbol = "ETH-USD" if "ETH-USD" in normalized else base_symbol
        base_close = pd.to_numeric(normalized[base_symbol]["close"], errors="coerce")
        base_ret = base_close.pct_change().replace([np.inf, -np.inf], np.nan)
        eth_close = pd.to_numeric(normalized[eth_symbol]["close"], errors="coerce")
        eth_ret = eth_close.pct_change().replace([np.inf, -np.inf], np.nan)

        out: dict[str, pd.DataFrame] = {}
        for symbol, frame in normalized.items():
            local = frame.copy()
            local_ret = pd.to_numeric(local["close"], errors="coerce").pct_change().replace([np.inf, -np.inf], np.nan)
            aligned_base = base_ret.reindex(local.index)
            aligned_eth = eth_ret.reindex(local.index)
            corr = local_ret.rolling(96).corr(aligned_base)
            corr = corr.replace([np.inf, -np.inf], np.nan).fillna(0.0)
            local["asset_correlation"] = corr
            corr_shift = corr.diff(8).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            local["rolling_correlation_shift"] = corr_shift
            local["asset_correlation_state"] = np.where(
                local["asset_correlation"] >= 0.70,
                "high_corr",
                np.where(local["asset_correlation"] <= 0.25, "decoupled", "neutral_corr"),
            )
            local["btc_lead_ret"] = aligned_base.shift(1).fillna(0.0)
            local["eth_lead_ret"] = aligned_eth.shift(1).fillna(0.0)
            local["lead_lag_residual"] = (local_ret - ((0.6 * local["btc_lead_ret"]) + (0.4 * local["eth_lead_ret"]))).fillna(0.0)
            local["correlation_breakdown_event"] = (
                (local["asset_correlation"] < 0.25) & (local["rolling_correlation_shift"] < -0.12)
            ).astype(float)
            out[symbol] = local
        return out

    @staticmethod
    def _safe_std(x: pd.Series) -> float:
        std = float(x.std()) if len(x) > 1 else 0.0
        if not np.isfinite(std):
            return 0.0
        return std

    @staticmethod
    def _session_label(df: pd.DataFrame) -> pd.Series:
        if "session_us" in df.columns and "session_eu" in df.columns:
            return pd.Series(
                np.where(
                df["session_us"] > 0.5,
                "us",
                np.where(df["session_eu"] > 0.5, "eu", "asia"),
                ),
                index=df.index,
            )
        hour = pd.DatetimeIndex(df.index).hour
        return pd.Series(
            np.where((hour >= 13) & (hour < 21), "us", np.where((hour >= 8) & (hour < 16), "eu", "asia")),
            index=df.index,
        )

    def _prepare_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy().sort_index()
        out.index = pd.DatetimeIndex(pd.to_datetime(out.index, utc=True))

        for col in ["open", "high", "low", "close", "volume"]:
            out[col] = pd.to_numeric(out[col], errors="coerce")

        out = FlowFeatureEngineer.enrich(out)

        if "long_short_ratio" not in out.columns:
            out["long_short_ratio"] = 1.0
        lsr = pd.to_numeric(out["long_short_ratio"], errors="coerce").replace(0.0, np.nan).fillna(1.0)
        lsr_std = lsr.rolling(96).std().replace(0.0, np.nan)
        out["long_short_ratio_z"] = ((lsr - lsr.rolling(96).mean()) / lsr_std).replace([np.inf, -np.inf], np.nan).fillna(0.0)

        ret1 = out["close"].pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
        out["ret1"] = ret1
        out["return_abs"] = ret1.abs()
        out["ret1_z"] = (
            (ret1 - ret1.rolling(96).mean()) / ret1.rolling(96).std().replace(0.0, np.nan)
        ).replace([np.inf, -np.inf], np.nan).fillna(0.0)

        vol_mean = out["volume"].rolling(48).mean().replace(0.0, np.nan)
        out["normalized_volume"] = (out["volume"] / vol_mean).replace([np.inf, -np.inf], np.nan).fillna(1.0)
        out["impact_score"] = (out["return_abs"] / out["normalized_volume"].replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)

        range_raw = (out["high"] - out["low"]).abs()
        body_raw = (out["close"] - out["open"]).abs()
        vol_denom = out["volume"].replace(0.0, np.nan)
        out["range_efficiency"] = (range_raw / vol_denom).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        out["trend_efficiency"] = (body_raw / vol_denom).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        out["efficiency_ratio"] = (
            out["trend_efficiency"] / out["range_efficiency"].replace(0.0, np.nan)
        ).replace([np.inf, -np.inf], np.nan).fillna(0.0)

        tr = pd.concat(
            [
                (out["high"] - out["low"]).abs(),
                (out["high"] - out["close"].shift(1)).abs(),
                (out["low"] - out["close"].shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)
        out["atr_short"] = tr.rolling(14).mean().bfill()
        out["atr_long"] = tr.rolling(50).mean().bfill()
        out["atr_ratio"] = (out["atr_short"] / out["atr_long"].replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(1.0)
        out["atr_ratio_delta"] = out["atr_ratio"].diff(4).fillna(0.0)
        out["compression"] = (out["atr_ratio"] < 0.90).astype(float)
        out["expansion"] = (out["atr_ratio"] > 1.12).astype(float)

        rolling_vol = ret1.rolling(20).std().fillna(0.0)
        out["regime"] = np.where(
            out["atr_ratio"] > 1.25,
            "high_volatility",
            np.where((out["close"].ewm(span=12, adjust=False).mean() - out["close"].ewm(span=26, adjust=False).mean()).abs() / out["close"].replace(0.0, np.nan) > 0.004, "trend", "range"),
        )
        out["volatility_state"] = np.where(out["atr_ratio"] < 0.92, "compression", "expansion")
        out["session"] = self._session_label(out)
        out["hour_bucket"] = pd.DatetimeIndex(out.index).hour.astype(int)
        out["weekday_type"] = np.where(pd.DatetimeIndex(out.index).dayofweek >= 5, "weekend", "weekday")

        open_ref = out["open"].replace(0.0, np.nan)
        out["body_return"] = ((out["close"] - out["open"]) / open_ref).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        out["realized_vol"] = rolling_vol
        vol_pct = out["realized_vol"].rolling(240).rank(pct=True)
        out["rolling_vol_percentile"] = vol_pct.fillna(0.5)
        out["rolling_range"] = ((out["high"].rolling(8).max() - out["low"].rolling(8).min()) / out["close"].replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        abs_ret = out["ret1"].abs()
        out["stagnation"] = (abs_ret < abs_ret.rolling(48).median().fillna(0.0)).astype(float)

        mom_fast = out["close"].pct_change(4).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        mom_slow = out["close"].pct_change(16).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        out["momentum_fast"] = mom_fast
        out["momentum_slow"] = mom_slow
        out["momentum_decay"] = (mom_fast - mom_slow).fillna(0.0)

        if "rolling_correlation_shift" not in out.columns:
            out["rolling_correlation_shift"] = 0.0
        if "lead_lag_residual" not in out.columns:
            out["lead_lag_residual"] = 0.0
        if "correlation_breakdown_event" not in out.columns:
            out["correlation_breakdown_event"] = 0.0

        out["swing_high_20"] = out["high"].rolling(20).max().shift(1)
        out["swing_low_20"] = out["low"].rolling(20).min().shift(1)
        out["breakout_up"] = (out["high"] > out["swing_high_20"]).astype(float)
        out["breakout_down"] = (out["low"] < out["swing_low_20"]).astype(float)
        out["breakout_failure_up"] = (((out["high"] > out["swing_high_20"]) & (out["close"] <= out["swing_high_20"])).fillna(False)).astype(float)
        out["breakout_failure_down"] = (((out["low"] < out["swing_low_20"]) & (out["close"] >= out["swing_low_20"])).fillna(False)).astype(float)

        # Realized follow-through and reversal response around breakout states (post-event diagnostics feature).
        out["follow_through_2h"] = out["close"].pct_change(2)
        out["follow_through_4h"] = out["close"].pct_change(4)
        out["follow_through_8h"] = out["close"].pct_change(8)
        out["follow_through_score"] = (
            out[["follow_through_2h", "follow_through_4h", "follow_through_8h"]].mean(axis=1)
        ).fillna(0.0)
        out["reversal_score"] = (-out["follow_through_score"]).fillna(0.0)

        ema12 = out["close"].ewm(span=12, adjust=False).mean()
        ema26 = out["close"].ewm(span=26, adjust=False).mean()
        out["trend_sign"] = np.sign((ema12 - ema26).fillna(0.0))

        # Execution-response layer from OHLCV + flow (no external L2 feed required).
        eps = 1e-9
        hl_range = (out["high"] - out["low"]).abs()
        body = (out["close"] - out["open"])
        body_abs = body.abs()
        vol_roll = out["volume"].rolling(48).mean().replace(0.0, np.nan)
        out["normalized_volume"] = (out["volume"] / vol_roll).replace([np.inf, -np.inf], np.nan).fillna(1.0)

        out["aggressor_score"] = (body / (hl_range + eps)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        out["aggressor_pressure"] = (out["aggressor_score"] * out["normalized_volume"]).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        out["absorption_score"] = (out["normalized_volume"] / (body_abs + eps)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        out["impact"] = (body_abs / (out["volume"] + eps)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        out["trend_efficiency"] = (body_abs / (hl_range + eps)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        out["range_efficiency"] = (hl_range / (out["volume"] + eps)).replace([np.inf, -np.inf], np.nan).fillna(0.0)

        # Forward response surfaces (used for event-state classification only in offline research).
        out["forward_return_2h"] = (out["close"].shift(-2) / out["close"] - 1.0).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        out["forward_return_4h"] = (out["close"].shift(-4) / out["close"] - 1.0).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        out["forward_return_8h"] = (out["close"].shift(-8) / out["close"] - 1.0).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        body_sign = pd.Series(np.sign(body.to_numpy()), index=out.index)
        out["follow_through_2h"] = body_sign.replace(0.0, np.nan).fillna(0.0) * out["forward_return_2h"]
        out["follow_through_4h"] = body_sign.replace(0.0, np.nan).fillna(0.0) * out["forward_return_4h"]
        out["follow_through_8h"] = body_sign.replace(0.0, np.nan).fillna(0.0) * out["forward_return_8h"]
        out["follow_through_signal"] = out[["follow_through_2h", "follow_through_4h", "follow_through_8h"]].mean(axis=1).fillna(0.0)

        # Synthetic orderbook / execution features derived from OHLCV candles.
        upper_wick = (out["high"] - pd.concat([out["open"], out["close"]], axis=1).max(axis=1)).clip(lower=0.0)
        lower_wick = (pd.concat([out["open"], out["close"]], axis=1).min(axis=1) - out["low"]).clip(lower=0.0)
        out["upper_wick"] = upper_wick
        out["lower_wick"] = lower_wick
        out["wick_pressure"] = ((lower_wick - upper_wick) / (hl_range + eps)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        out["directionality"] = (body / (hl_range + eps)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        out["acceptance_score"] = (body_abs / (hl_range + eps)).replace([np.inf, -np.inf], np.nan).fillna(0.0)

        vol_mean = out["volume"].rolling(72).mean()
        vol_std = out["volume"].rolling(72).std().replace(0.0, np.nan)
        out["volume_z"] = ((out["volume"] - vol_mean) / vol_std).replace([np.inf, -np.inf], np.nan).fillna(0.0)

        q_low_range = hl_range.rolling(120).quantile(0.35).fillna(hl_range.median())
        q_high_range = hl_range.rolling(120).quantile(0.65).fillna(hl_range.median())
        q_high_vol = out["normalized_volume"].rolling(120).quantile(0.65).fillna(1.0)
        q_low_vol = out["normalized_volume"].rolling(120).quantile(0.35).fillna(1.0)
        absorption_regime = (hl_range <= q_low_range) & (out["normalized_volume"] >= q_high_vol)
        inefficient_regime = (hl_range >= q_high_range) & (out["normalized_volume"] <= q_low_vol)
        expansion_regime = (hl_range >= q_high_range) & (out["normalized_volume"] >= q_high_vol)
        out["micro_regime"] = np.where(absorption_regime, "absorption", np.where(inefficient_regime, "inefficient", np.where(expansion_regime, "expansion", "neutral")))

        # Event sequencing signals for synthetic execution dynamics.
        wick_dom = out["wick_pressure"].abs() > out["wick_pressure"].abs().rolling(72).quantile(0.65).fillna(out["wick_pressure"].abs().median())
        same_wick_sign = pd.Series(np.sign(out["wick_pressure"].to_numpy()), index=out.index).replace(0.0, np.nan).ffill().fillna(0.0)
        out["consecutive_wick_dominance"] = (wick_dom & (same_wick_sign == same_wick_sign.shift(1))).astype(float)

        vol_shock = out["volume_z"] > out["volume_z"].rolling(72).quantile(0.70).fillna(0.0)
        out["volume_shock_cluster"] = vol_shock.rolling(6).sum().fillna(0.0)

        rejection_bar = (out["acceptance_score"] < out["acceptance_score"].rolling(72).quantile(0.40).fillna(out["acceptance_score"].median())) & (out["wick_pressure"].abs() > out["wick_pressure"].abs().rolling(72).median().fillna(out["wick_pressure"].abs().median()))
        reversal_bar = (out["follow_through_signal"] < 0.0)
        out["expansion_rejection_reversal"] = (expansion_regime.shift(1).fillna(False) & rejection_bar & reversal_bar).astype(float)

        if "asset_correlation" not in out.columns:
            out["asset_correlation"] = 0.0
        if "asset_correlation_state" not in out.columns:
            out["asset_correlation_state"] = "neutral_corr"

        spread_proxy_bps = ((out["high"] - out["low"]) / out["close"].replace(0.0, np.nan) * 10000.0).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        out["spread_proxy_bps"] = spread_proxy_bps

        trade_impact_eff = pd.to_numeric(
            out["trade_impact_efficiency_5s"] if "trade_impact_efficiency_5s" in out.columns else pd.Series(0.0, index=out.index),
            errors="coerce",
        ).fillna(0.0)
        value_area_distance = pd.to_numeric(
            out["value_area_distance"] if "value_area_distance" in out.columns else pd.Series(0.0, index=out.index),
            errors="coerce",
        ).fillna(0.0)
        micro_dislocation_bps = (trade_impact_eff.abs() + value_area_distance.abs()) * 10000.0
        fee_bps = 7.0
        latency_penalty_bps = pd.to_numeric(
            out["trade_time_since_shock_1m"] if "trade_time_since_shock_1m" in out.columns else pd.Series(0.0, index=out.index),
            errors="coerce",
        ).fillna(0.0).clip(lower=0.0, upper=120.0) * 0.02
        out["cross_venue_gross_edge_bps"] = micro_dislocation_bps
        out["cross_venue_net_edge_bps"] = (micro_dislocation_bps - fee_bps - latency_penalty_bps).fillna(0.0)
        fill_penalty = (spread_proxy_bps / 25.0).clip(lower=0.0, upper=0.6)
        trade_imbalance = pd.to_numeric(
            out["trade_imbalance_5s"] if "trade_imbalance_5s" in out.columns else pd.Series(0.0, index=out.index),
            errors="coerce",
        ).fillna(0.0)
        imbalance_penalty = trade_imbalance.abs().clip(0.0, 1.0) * 0.25
        out["hedge_fill_probability"] = (1.0 - fill_penalty - imbalance_penalty).clip(lower=0.05, upper=0.99)

        return out.replace([np.inf, -np.inf], np.nan).dropna()

    @staticmethod
    def _forward_returns(close: pd.Series, horizon: int) -> pd.Series:
        return (close.shift(-horizon) / close - 1.0).replace([np.inf, -np.inf], np.nan)

    def _event_masks(self, f: pd.DataFrame) -> dict[str, pd.Series]:
        def _series_col(name: str, default: float = 0.0) -> pd.Series:
            if name in f.columns:
                return pd.to_numeric(f[name], errors="coerce").fillna(default)
            return pd.Series(default, index=f.index)

        liq_z = _series_col("liquidation_z")
        liq_imb = _series_col("liquidation_imbalance")
        oi_z = _series_col("oi_delta_z")
        funding_z = _series_col("funding_z")
        trend_sign = _series_col("trend_sign")
        vol_n = _series_col("normalized_volume", default=1.0)
        aggressor_pressure = _series_col("aggressor_pressure")
        absorption_score = _series_col("absorption_score")
        impact = _series_col("impact")
        trend_efficiency = _series_col("trend_efficiency")
        range_efficiency = _series_col("range_efficiency")
        follow_through_signal = _series_col("follow_through_signal")
        body_ret = _series_col("body_return")
        wick_pressure = _series_col("wick_pressure")
        directionality = _series_col("directionality")
        acceptance_score = _series_col("acceptance_score")
        volume_z = _series_col("volume_z")
        consecutive_wick_dominance = _series_col("consecutive_wick_dominance")
        volume_shock_cluster = _series_col("volume_shock_cluster")
        expansion_rejection_reversal = _series_col("expansion_rejection_reversal") > 0.5
        asset_corr = _series_col("asset_correlation")
        micro_regime = f["micro_regime"] if "micro_regime" in f.columns else pd.Series("neutral", index=f.index)

        # Trade-level execution features (from Binance aggTrades aggregation layer).
        trade_sv_1m = _series_col("trade_signed_volume_1m")
        trade_sv_10s = _series_col("trade_signed_volume_10s")
        trade_imb_1m = _series_col("trade_imbalance_1m")
        trade_imb_5s = _series_col("trade_imbalance_5s")
        trade_impact_1m = _series_col("trade_impact_1m")
        trade_impact_5s = _series_col("trade_impact_5s")
        trade_impact_eff_5s = _series_col("trade_impact_efficiency_5s")
        trade_recovery_1m = _series_col("trade_recovery_1m")
        trade_sv_z_1m = _series_col("trade_signed_volume_z_1m")
        trade_sweep_1m = _series_col("trade_sweep_flag_1m")
        trade_absorb_1m = _series_col("trade_absorption_flag_1m")
        trade_exhaust_1m = _series_col("trade_exhaustion_flag_1m")
        trade_cluster_1m = _series_col("trade_shock_cluster_1m")
        trade_time_since_shock = _series_col("trade_time_since_shock_1m")
        trade_burst_5s = _series_col("trade_aggression_burst_5s")
        trade_sweep_5s = _series_col("trade_sweep_detection_5s")
        trade_absorption_5s = _series_col("trade_absorption_5s")
        event_a = _series_col("trade_event_a_buy_sweep")
        event_b = _series_col("trade_event_b_sell_sweep")
        event_c = _series_col("trade_event_c_absorption")
        event_d = _series_col("trade_event_d_exhaustion")
        event_a_resp = _series_col("trade_event_a_response_score")
        event_b_resp = _series_col("trade_event_b_response_score")
        event_c_resp = _series_col("trade_event_c_response_score")
        event_d_resp = _series_col("trade_event_d_response_score")
        seq_burst_burst_cont = _series_col("trade_sequence_burst_burst_continuation")
        seq_burst_absorb_rev = _series_col("trade_sequence_burst_absorption_reversal")
        spread_proxy_bps = _series_col("spread_proxy_bps")
        cross_venue_net_edge_bps = _series_col("cross_venue_net_edge_bps")
        hedge_fill_probability = _series_col("hedge_fill_probability", default=0.5)
        vol_pct = _series_col("rolling_vol_percentile", default=0.5)
        ret1_z = _series_col("ret1_z")
        momentum_decay = _series_col("momentum_decay")
        corr_shift = _series_col("rolling_correlation_shift")
        lead_lag_residual = _series_col("lead_lag_residual")
        corr_breakdown = _series_col("correlation_breakdown_event") > 0.5

        compression = _series_col("compression") > 0.5
        expansion = _series_col("expansion") > 0.5
        atr_delta = _series_col("atr_ratio_delta")
        breakout_up = _series_col("breakout_up") > 0.5
        breakout_down = _series_col("breakout_down") > 0.5
        breakout_fail_up = _series_col("breakout_failure_up") > 0.5
        breakout_fail_down = _series_col("breakout_failure_down") > 0.5

        # Quantile-normalized response states (broad core, strict overlays).
        q = lambda s, p: float(s.quantile(p)) if len(s) > 0 else 0.0
        strong_buy_pressure = aggressor_pressure > q(aggressor_pressure, 0.60)
        strong_sell_pressure = aggressor_pressure < q(aggressor_pressure, 0.40)
        high_absorb = absorption_score > q(absorption_score, 0.60)
        high_impact = impact > q(impact, 0.45)
        low_impact = impact < q(impact, 0.42)
        high_trend_eff = trend_efficiency > q(trend_efficiency, 0.45)
        low_move = body_ret.abs() < body_ret.abs().rolling(72).median().fillna(body_ret.abs().median())
        high_volume = vol_n > q(vol_n, 0.58)

        # Flow alignment score.
        liq_component = pd.Series(np.tanh((liq_imb * 2.0).to_numpy()), index=f.index)
        oi_component = pd.Series(np.tanh((oi_z * 0.8).to_numpy()), index=f.index)
        funding_component = pd.Series(-np.tanh((funding_z * 0.9).to_numpy()), index=f.index)
        flow_alignment_score = (liq_component * 0.45) + (oi_component * 0.35) + (funding_component * 0.20)
        align_signs = pd.concat([liq_component, oi_component, funding_component], axis=1).apply(np.sign).replace(0.0, np.nan)
        align_agreement = align_signs.mean(axis=1).abs().fillna(0.0)
        align_long = (flow_alignment_score > 0.02) & (align_agreement > 0.10)
        align_short = (flow_alignment_score < -0.02) & (align_agreement > 0.10)

        # Event sequencing states.
        vol_spike = vol_n > q(vol_n, 0.68)
        spike_cluster_6 = vol_spike.rolling(6).sum().fillna(0.0)
        spike_cluster_12 = vol_spike.rolling(12).sum().fillna(0.0)
        spike_int = vol_spike.astype(int)
        time_since_spike = (~vol_spike).astype(int).groupby(spike_int.cumsum()).cumsum()

        liq_spike = liq_z > q(liq_z, 0.65)
        liq_cluster_6 = liq_spike.rolling(6).sum().fillna(0.0)
        liq_second_spike = liq_spike & liq_spike.shift(1)

        breakout_any = breakout_up | breakout_down
        breakout_int = breakout_any.astype(int)
        time_since_breakout = (~breakout_any).astype(int).groupby(breakout_int.cumsum()).cumsum()

        # CASE A continuation: high flow + high impact + high efficiency.
        aggressive_cont_long_core = strong_buy_pressure & high_impact & high_trend_eff & ((trend_sign > 0) | (body_ret > 0))
        aggressive_cont_short_core = strong_sell_pressure & high_impact & high_trend_eff & ((trend_sign < 0) | (body_ret < 0))
        aggressive_cont_long_opt = aggressive_cont_long_core & align_long
        aggressive_cont_short_opt = aggressive_cont_short_core & align_short

        # CASE B absorption: high volume + low impact + low move => reversal.
        absorption_reversal_long_core = high_absorb & low_impact & low_move & high_volume & (body_ret < 0)
        absorption_reversal_short_core = high_absorb & low_impact & low_move & high_volume & (body_ret > 0)
        absorption_reversal_long_opt = absorption_reversal_long_core & align_long
        absorption_reversal_short_opt = absorption_reversal_short_core & align_short

        # CASE C trap: breakout with poor follow-through or reversal.
        trap_breakout_short_core = breakout_up & (follow_through_signal <= 0.0)
        trap_breakout_long_core = breakout_down & (follow_through_signal <= 0.0)
        trap_breakout_short_opt = trap_breakout_short_core & (time_since_breakout <= 3)
        trap_breakout_long_opt = trap_breakout_long_core & (time_since_breakout <= 3)

        # Exhaustion trap: spike cluster >= 2, impact decaying, follow-through negative.
        impact_decay = impact < impact.shift(1)
        exhaustion_trap_short_core = (spike_cluster_6 >= 2.0) & impact_decay & (follow_through_signal < 0.0) & (body_ret > 0)
        exhaustion_trap_long_core = (spike_cluster_6 >= 2.0) & impact_decay & (follow_through_signal < 0.0) & (body_ret < 0)
        exhaustion_trap_short_opt = exhaustion_trap_short_core & (time_since_spike <= 2)
        exhaustion_trap_long_opt = exhaustion_trap_long_core & (time_since_spike <= 2)

        # Transition patterns.
        transition_compress_expand_failure = compression.shift(1) & expansion & (atr_delta > 0.06) & (breakout_fail_up | breakout_fail_down)
        transition_spike_spike_exhaust = (liq_cluster_6 >= 2.0) & (liq_second_spike | (spike_cluster_6 >= 3.0)) & (follow_through_signal <= 0.0)
        transition_breakout_no_followthrough = breakout_any & (time_since_breakout <= 3) & (follow_through_signal <= 0.0)

        # Regime-conditioned execution response composites.
        regime_trend = f["regime"] == "trend"
        regime_range = f["regime"] == "range"
        session_us = f["session"] == "us"
        session_asia = f["session"] == "asia"
        vol_expansion = f["volatility_state"] == "expansion"
        vol_compression = f["volatility_state"] == "compression"

        regime_trend_us_cont_long = regime_trend & session_us & vol_expansion & aggressive_cont_long_core
        regime_trend_us_cont_short = regime_trend & session_us & vol_expansion & aggressive_cont_short_core
        regime_range_asia_absorb_long = regime_range & session_asia & vol_compression & absorption_reversal_long_core
        regime_range_asia_absorb_short = regime_range & session_asia & vol_compression & absorption_reversal_short_core

        # Synthetic microstructure families from OHLCV approximations.
        wick_strength = wick_pressure.abs() > q(wick_pressure.abs(), 0.60)
        high_volume_shock = volume_z > q(volume_z, 0.60)
        low_acceptance = acceptance_score < q(acceptance_score, 0.45)
        high_acceptance = acceptance_score > q(acceptance_score, 0.55)
        large_move = body_ret.abs() > q(body_ret.abs(), 0.60)
        low_volume_support = volume_z < q(volume_z, 0.40)
        dir_positive = directionality > q(directionality, 0.55)
        dir_negative = directionality < q(directionality, 0.45)
        aligned_volume = volume_z > q(volume_z, 0.50)

        # EDGE 1: Wick Absorption Reversal (direction = wick sign).
        edge_wick_absorb_long_core = wick_strength & high_volume_shock & low_acceptance & (wick_pressure > 0.0)
        edge_wick_absorb_short_core = wick_strength & high_volume_shock & low_acceptance & (wick_pressure < 0.0)
        edge_wick_absorb_long_opt = edge_wick_absorb_long_core & (micro_regime == "absorption") & (consecutive_wick_dominance > 0.5)
        edge_wick_absorb_short_opt = edge_wick_absorb_short_core & (micro_regime == "absorption") & (consecutive_wick_dominance > 0.5)

        # EDGE 2: Inefficiency Reversion (direction = opposite move).
        edge_ineff_revert_long_core = large_move & low_volume_support & (body_ret < 0.0)
        edge_ineff_revert_short_core = large_move & low_volume_support & (body_ret > 0.0)
        edge_ineff_revert_long_opt = edge_ineff_revert_long_core & (micro_regime == "inefficient") & (volume_shock_cluster >= 2.0)
        edge_ineff_revert_short_opt = edge_ineff_revert_short_core & (micro_regime == "inefficient") & (volume_shock_cluster >= 2.0)

        # EDGE 3: Efficient Continuation (direction = move).
        edge_eff_cont_long_core = dir_positive & high_acceptance & aligned_volume & (body_ret > 0.0)
        edge_eff_cont_short_core = dir_negative & high_acceptance & aligned_volume & (body_ret < 0.0)
        edge_eff_cont_long_opt = edge_eff_cont_long_core & (micro_regime == "expansion")
        edge_eff_cont_short_opt = edge_eff_cont_short_core & (micro_regime == "expansion")

        # Sequencing: expansion -> rejection -> reversal and repeated wick/volume pressure.
        edge_seq_expansion_rejection_reversal = expansion_rejection_reversal
        edge_seq_wick_dominance_cluster_long = (consecutive_wick_dominance > 0.5) & (wick_pressure > 0.0) & (volume_shock_cluster >= 2.0)
        edge_seq_wick_dominance_cluster_short = (consecutive_wick_dominance > 0.5) & (wick_pressure < 0.0) & (volume_shock_cluster >= 2.0)

        # Real execution-driven alpha families using trade-level aggressor dynamics.
        sv_buy_q = q(trade_sv_1m, 0.70)
        sv_sell_q = q(trade_sv_1m, 0.30)
        impact_q_hi = q(trade_impact_1m, 0.60)
        impact_q_lo = q(trade_impact_1m, 0.40)
        strong_buy_aggr = (trade_sv_1m > sv_buy_q) & (trade_imb_1m > q(trade_imb_1m, 0.60))
        strong_sell_aggr = (trade_sv_1m < sv_sell_q) & (trade_imb_1m < q(trade_imb_1m, 0.40))
        strong_impact_exec = trade_impact_1m > impact_q_hi
        weak_impact_exec = trade_impact_1m < impact_q_lo
        repeated_sweeps = trade_sweep_1m > q(trade_sweep_1m, 0.55)
        weakening_impact = trade_impact_1m < trade_impact_1m.shift(1)

        # Execution events from sub-minute modeling (A-D) + response model.
        event_a_active = event_a > 0.0
        event_b_active = event_b > 0.0
        event_c_active = event_c > 0.0
        event_d_active = event_d > 0.0

        event_a_cont_response = event_a_resp > q(event_a_resp, 0.55)
        event_b_cont_response = event_b_resp < q(event_b_resp, 0.45)
        event_c_rev_response_long = event_c_resp > q(event_c_resp, 0.60)
        event_c_rev_response_short = event_c_resp < q(event_c_resp, 0.40)
        event_d_trap_response_long = event_d_resp > q(event_d_resp, 0.55)
        event_d_trap_response_short = event_d_resp < q(event_d_resp, 0.45)

        event_high_impact = trade_impact_5s > q(trade_impact_5s, 0.60)
        event_low_impact = trade_impact_5s < q(trade_impact_5s, 0.40)
        event_strong_buy = (trade_imb_5s > q(trade_imb_5s, 0.65)) | (trade_sv_10s > q(trade_sv_10s, 0.70))
        event_strong_sell = (trade_imb_5s < q(trade_imb_5s, 0.35)) | (trade_sv_10s < q(trade_sv_10s, 0.30))

        # Requested edge families.
        edge_exec_sweep_cont_long = event_a_active & event_strong_buy & event_high_impact & event_a_cont_response
        edge_exec_sweep_cont_short = event_b_active & event_strong_sell & event_high_impact & event_b_cont_response

        edge_exec_absorb_rev_long = event_c_active & event_strong_sell & event_low_impact & event_c_rev_response_long
        edge_exec_absorb_rev_short = event_c_active & event_strong_buy & event_low_impact & event_c_rev_response_short

        edge_exec_exhaust_trap_long = event_d_active & event_strong_sell & (trade_impact_eff_5s < q(trade_impact_eff_5s, 0.40)) & event_d_trap_response_long
        edge_exec_exhaust_trap_short = event_d_active & event_strong_buy & (trade_impact_eff_5s > q(trade_impact_eff_5s, 0.60)) & event_d_trap_response_short

        # Requested sequence logic.
        edge_exec_sequence_burst_burst_cont_long = (seq_burst_burst_cont > 0.0) & event_strong_buy & event_a_cont_response
        edge_exec_sequence_burst_burst_cont_short = (seq_burst_burst_cont > 0.0) & event_strong_sell & event_b_cont_response
        edge_exec_sequence_burst_absorb_rev_long = (seq_burst_absorb_rev > 0.0) & edge_exec_absorb_rev_long
        edge_exec_sequence_burst_absorb_rev_short = (seq_burst_absorb_rev > 0.0) & edge_exec_absorb_rev_short

        deriv_long_align = (oi_z > q(oi_z, 0.55)) & (liq_imb > q(liq_imb, 0.55)) & (funding_z > q(funding_z, 0.50))
        deriv_short_align = (oi_z < q(oi_z, 0.45)) & (liq_imb < q(liq_imb, 0.45)) & (funding_z < q(funding_z, 0.50))

        # EDGE 1: Aggressor Continuation.
        edge_exec_aggr_cont_long_core = strong_buy_aggr & strong_impact_exec
        edge_exec_aggr_cont_short_core = strong_sell_aggr & strong_impact_exec
        edge_exec_aggr_cont_long_opt = edge_exec_aggr_cont_long_core & deriv_long_align & (trade_time_since_shock <= 2.0)
        edge_exec_aggr_cont_short_opt = edge_exec_aggr_cont_short_core & deriv_short_align & (trade_time_since_shock <= 2.0)

        # EDGE 2: Absorption Reversal.
        edge_exec_absorb_reversal_long_core = strong_sell_aggr & weak_impact_exec & ((trade_absorb_1m > 0.0) | (trade_recovery_1m > 0.0))
        edge_exec_absorb_reversal_short_core = strong_buy_aggr & weak_impact_exec & ((trade_absorb_1m > 0.0) | (trade_recovery_1m < 0.0))
        edge_exec_absorb_reversal_long_opt = edge_exec_absorb_reversal_long_core & (liq_z > q(liq_z, 0.55))
        edge_exec_absorb_reversal_short_opt = edge_exec_absorb_reversal_short_core & (liq_z > q(liq_z, 0.55))

        # EDGE 3: Exhaustion Trap.
        edge_exec_exhaustion_trap_long_core = strong_sell_aggr & repeated_sweeps & weakening_impact & ((trade_exhaust_1m > 0.0) | (trade_recovery_1m > 0.0))
        edge_exec_exhaustion_trap_short_core = strong_buy_aggr & repeated_sweeps & weakening_impact & ((trade_exhaust_1m > 0.0) | (trade_recovery_1m < 0.0))
        edge_exec_exhaustion_trap_long_opt = edge_exec_exhaustion_trap_long_core & (trade_time_since_shock <= 3.0) & (liq_z > q(liq_z, 0.55))
        edge_exec_exhaustion_trap_short_opt = edge_exec_exhaustion_trap_short_core & (trade_time_since_shock <= 3.0) & (liq_z > q(liq_z, 0.55))

        # Sequence modeling.
        edge_exec_sequence_sweep_sweep_continuation_long = (trade_sweep_1m.rolling(3).mean() > q(trade_sweep_1m, 0.55)) & strong_buy_aggr & strong_impact_exec
        edge_exec_sequence_sweep_sweep_continuation_short = (trade_sweep_1m.rolling(3).mean() > q(trade_sweep_1m, 0.55)) & strong_sell_aggr & strong_impact_exec
        edge_exec_sequence_sweep_absorb_reversal_long = (trade_sweep_1m.shift(1) > 0.0) & (trade_absorb_1m > 0.0) & edge_exec_absorb_reversal_long_core
        edge_exec_sequence_sweep_absorb_reversal_short = (trade_sweep_1m.shift(1) > 0.0) & (trade_absorb_1m > 0.0) & edge_exec_absorb_reversal_short_core

        # PHASE 1 FAMILY 1: Cross-venue inefficiency (proxy with latency-adjusted, fee-adjusted dislocation).
        dislocation_ready = (cross_venue_net_edge_bps > q(cross_venue_net_edge_bps, 0.60)) & (hedge_fill_probability > 0.65)
        value_area_distance_col = _series_col("value_area_distance")
        cv_long_bias = (value_area_distance_col < q(value_area_distance_col, 0.40)) & (trade_imb_5s > q(trade_imb_5s, 0.55))
        cv_short_bias = (value_area_distance_col > q(value_area_distance_col, 0.60)) & (trade_imb_5s < q(trade_imb_5s, 0.45))
        edge_cross_venue_inefficiency_long = dislocation_ready & cv_long_bias
        edge_cross_venue_inefficiency_short = dislocation_ready & cv_short_bias

        # PHASE 1 FAMILY 2: Liquidity imbalance proxies.
        burst_proxy = (volume_z > q(volume_z, 0.60)) | (trade_burst_5s > q(trade_burst_5s, 0.60))
        spread_widen_proxy = spread_proxy_bps > q(spread_proxy_bps, 0.60)
        impact_asymmetry = trade_impact_eff_5s * trade_imb_5s
        edge_liquidity_imbalance_long = burst_proxy & spread_widen_proxy & (impact_asymmetry > q(impact_asymmetry, 0.60))
        edge_liquidity_imbalance_short = burst_proxy & spread_widen_proxy & (impact_asymmetry < q(impact_asymmetry, 0.40))

        # PHASE 1 FAMILY 3: Volatility regime breaks.
        compression_to_expansion = compression.shift(1).fillna(False) & expansion & (atr_delta > q(atr_delta, 0.60))
        expansion_to_exhaustion = expansion & (trade_impact_1m < trade_impact_1m.shift(1)) & (follow_through_signal < 0.0)
        edge_volatility_regime_break_long = compression_to_expansion & ((trend_sign > 0) | (trade_sv_z_1m > 0.0))
        edge_volatility_regime_break_short = (compression_to_expansion & ((trend_sign < 0) | (trade_sv_z_1m < 0.0))) | expansion_to_exhaustion

        # PHASE 1 FAMILY 4: Funding + positioning pressure (crowding unwind).
        funding_extreme_high = funding_z > q(funding_z, 0.70)
        funding_extreme_low = funding_z < q(funding_z, 0.30)
        oi_expansion = oi_z > q(oi_z, 0.65)
        price_stagnation = _series_col("stagnation") > 0.5
        edge_funding_positioning_unwind_short = funding_extreme_high & oi_expansion & price_stagnation & (liq_imb > q(liq_imb, 0.55))
        edge_funding_positioning_unwind_long = funding_extreme_low & oi_expansion & price_stagnation & (liq_imb < q(liq_imb, 0.45))

        # Mid-frequency domain shift families.
        vol_compress = (vol_pct < 0.25) & compression
        vol_expand = (vol_pct > 0.65) & expansion
        vol_exhaust = vol_expand & (momentum_decay < q(momentum_decay, 0.35))
        edge_mf_vol_transition_long = vol_compress.shift(1).fillna(False) & vol_expand & (ret1_z > q(ret1_z, 0.55))
        edge_mf_vol_transition_short = (vol_compress.shift(1).fillna(False) & vol_expand & (ret1_z < q(ret1_z, 0.45))) | vol_exhaust

        crowding_long = (funding_z > q(funding_z, 0.72)) & (oi_z > q(oi_z, 0.68)) & price_stagnation
        crowding_short = (funding_z < q(funding_z, 0.28)) & (oi_z > q(oi_z, 0.68)) & price_stagnation
        edge_mf_funding_positioning_unwind_short = crowding_long & (momentum_decay < q(momentum_decay, 0.40))
        edge_mf_funding_positioning_unwind_long = crowding_short & (momentum_decay > q(momentum_decay, 0.60))

        edge_mf_cross_asset_leadlag_long = (lead_lag_residual < q(lead_lag_residual, 0.35)) & (corr_shift > q(corr_shift, 0.55))
        edge_mf_cross_asset_leadlag_short = (lead_lag_residual > q(lead_lag_residual, 0.65)) & (corr_shift < q(corr_shift, 0.45))
        edge_mf_cross_asset_breakdown_long = corr_breakdown & (lead_lag_residual < q(lead_lag_residual, 0.40))
        edge_mf_cross_asset_breakdown_short = corr_breakdown & (lead_lag_residual > q(lead_lag_residual, 0.60))

        low_liq = (spread_proxy_bps > q(spread_proxy_bps, 0.62)) & (vol_pct > 0.60)
        high_liq = (spread_proxy_bps < q(spread_proxy_bps, 0.35)) & (vol_pct < 0.50)
        edge_mf_liquidity_regime_long = low_liq & (ret1_z > q(ret1_z, 0.55)) & high_volume
        edge_mf_liquidity_regime_short = low_liq & (ret1_z < q(ret1_z, 0.45)) & high_volume
        edge_mf_liquidity_meanrev_long = high_liq & (ret1_z < q(ret1_z, 0.35))
        edge_mf_liquidity_meanrev_short = high_liq & (ret1_z > q(ret1_z, 0.65))

        # Keep event families broad for statistical power; optional overlays add precision variants.
        masks: dict[str, pd.Series | np.ndarray[Any, Any]] = {
            # EDGE 1: Absorption reversal
            "edge_absorption_reversal_long_core": absorption_reversal_long_core,
            "edge_absorption_reversal_short_core": absorption_reversal_short_core,
            "edge_absorption_reversal_long_opt": absorption_reversal_long_opt,
            "edge_absorption_reversal_short_opt": absorption_reversal_short_opt,

            # EDGE 2: Aggressive continuation
            "edge_aggressive_continuation_long_core": aggressive_cont_long_core,
            "edge_aggressive_continuation_short_core": aggressive_cont_short_core,
            "edge_aggressive_continuation_long_opt": aggressive_cont_long_opt,
            "edge_aggressive_continuation_short_opt": aggressive_cont_short_opt,

            # EDGE 3: Exhaustion trap
            "edge_exhaustion_trap_long_core": exhaustion_trap_long_core,
            "edge_exhaustion_trap_short_core": exhaustion_trap_short_core,
            "edge_exhaustion_trap_long_opt": exhaustion_trap_long_opt,
            "edge_exhaustion_trap_short_opt": exhaustion_trap_short_opt,

            # Trap and transition responses
            "edge_breakout_trap_long_core": trap_breakout_long_core,
            "edge_breakout_trap_short_core": trap_breakout_short_core,
            "edge_breakout_trap_long_opt": trap_breakout_long_opt,
            "edge_breakout_trap_short_opt": trap_breakout_short_opt,
            "edge_transition_compress_expand_failure": transition_compress_expand_failure,
            "edge_transition_spike_spike_exhaustion": transition_spike_spike_exhaust,
            "edge_transition_breakout_no_followthrough": transition_breakout_no_followthrough,

            # Regime-conditioned execution responses
            "edge_regime_trend_us_continuation_long": regime_trend_us_cont_long,
            "edge_regime_trend_us_continuation_short": regime_trend_us_cont_short,
            "edge_regime_range_asia_absorption_long": regime_range_asia_absorb_long,
            "edge_regime_range_asia_absorption_short": regime_range_asia_absorb_short,

            # Family-level broad alignment for minimum event flow
            "edge_flow_alignment_long": align_long,
            "edge_flow_alignment_short": align_short,
            "edge_spike_cluster_broad": spike_cluster_12 >= 3.0,
            "edge_high_volume_broad": high_volume,

            # Synthetic OHLCV microstructure families
            "edge_wick_absorption_reversal_long_core": edge_wick_absorb_long_core,
            "edge_wick_absorption_reversal_short_core": edge_wick_absorb_short_core,
            "edge_wick_absorption_reversal_long_opt": edge_wick_absorb_long_opt,
            "edge_wick_absorption_reversal_short_opt": edge_wick_absorb_short_opt,
            "edge_inefficiency_reversion_long_core": edge_ineff_revert_long_core,
            "edge_inefficiency_reversion_short_core": edge_ineff_revert_short_core,
            "edge_inefficiency_reversion_long_opt": edge_ineff_revert_long_opt,
            "edge_inefficiency_reversion_short_opt": edge_ineff_revert_short_opt,
            "edge_efficient_continuation_long_core": edge_eff_cont_long_core,
            "edge_efficient_continuation_short_core": edge_eff_cont_short_core,
            "edge_efficient_continuation_long_opt": edge_eff_cont_long_opt,
            "edge_efficient_continuation_short_opt": edge_eff_cont_short_opt,
            "edge_sequence_expansion_rejection_reversal": edge_seq_expansion_rejection_reversal,
            "edge_sequence_wick_dominance_cluster_long": edge_seq_wick_dominance_cluster_long,
            "edge_sequence_wick_dominance_cluster_short": edge_seq_wick_dominance_cluster_short,

            # Trade-level microstructure execution families
            "edge_exec_aggressor_continuation_long_core": edge_exec_aggr_cont_long_core,
            "edge_exec_aggressor_continuation_short_core": edge_exec_aggr_cont_short_core,
            "edge_exec_aggressor_continuation_long_opt": edge_exec_aggr_cont_long_opt,
            "edge_exec_aggressor_continuation_short_opt": edge_exec_aggr_cont_short_opt,
            "edge_exec_absorption_reversal_long_core": edge_exec_absorb_reversal_long_core,
            "edge_exec_absorption_reversal_short_core": edge_exec_absorb_reversal_short_core,
            "edge_exec_absorption_reversal_long_opt": edge_exec_absorb_reversal_long_opt,
            "edge_exec_absorption_reversal_short_opt": edge_exec_absorb_reversal_short_opt,
            "edge_exec_exhaustion_trap_long_core": edge_exec_exhaustion_trap_long_core,
            "edge_exec_exhaustion_trap_short_core": edge_exec_exhaustion_trap_short_core,
            "edge_exec_exhaustion_trap_long_opt": edge_exec_exhaustion_trap_long_opt,
            "edge_exec_exhaustion_trap_short_opt": edge_exec_exhaustion_trap_short_opt,
            "edge_exec_sequence_sweep_sweep_continuation_long": edge_exec_sequence_sweep_sweep_continuation_long,
            "edge_exec_sequence_sweep_sweep_continuation_short": edge_exec_sequence_sweep_sweep_continuation_short,
            "edge_exec_sequence_sweep_absorb_reversal_long": edge_exec_sequence_sweep_absorb_reversal_long,
            "edge_exec_sequence_sweep_absorb_reversal_short": edge_exec_sequence_sweep_absorb_reversal_short,
            "edge_exec_event_a_buy_sweep": event_a_active,
            "edge_exec_event_b_sell_sweep": event_b_active,
            "edge_exec_event_c_absorption": event_c_active,
            "edge_exec_event_d_exhaustion": event_d_active,
            "edge_exec_sweep_continuation_long": edge_exec_sweep_cont_long,
            "edge_exec_sweep_continuation_short": edge_exec_sweep_cont_short,
            "edge_exec_absorption_reversal_event_long": edge_exec_absorb_rev_long,
            "edge_exec_absorption_reversal_event_short": edge_exec_absorb_rev_short,
            "edge_exec_exhaustion_trap_event_long": edge_exec_exhaust_trap_long,
            "edge_exec_exhaustion_trap_event_short": edge_exec_exhaust_trap_short,
            "edge_exec_sequence_burst_burst_continuation_long": edge_exec_sequence_burst_burst_cont_long,
            "edge_exec_sequence_burst_burst_continuation_short": edge_exec_sequence_burst_burst_cont_short,
            "edge_exec_sequence_burst_absorption_reversal_long": edge_exec_sequence_burst_absorb_rev_long,
            "edge_exec_sequence_burst_absorption_reversal_short": edge_exec_sequence_burst_absorb_rev_short,

            # New market-structure families.
            "edge_cross_venue_inefficiency_long": edge_cross_venue_inefficiency_long,
            "edge_cross_venue_inefficiency_short": edge_cross_venue_inefficiency_short,
            "edge_liquidity_imbalance_long": edge_liquidity_imbalance_long,
            "edge_liquidity_imbalance_short": edge_liquidity_imbalance_short,
            "edge_volatility_regime_break_long": edge_volatility_regime_break_long,
            "edge_volatility_regime_break_short": edge_volatility_regime_break_short,
            "edge_funding_positioning_unwind_long": edge_funding_positioning_unwind_long,
            "edge_funding_positioning_unwind_short": edge_funding_positioning_unwind_short,

            # Mid-frequency structure domain families.
            "edge_mf_vol_transition_long": edge_mf_vol_transition_long,
            "edge_mf_vol_transition_short": edge_mf_vol_transition_short,
            "edge_mf_funding_positioning_unwind_long": edge_mf_funding_positioning_unwind_long,
            "edge_mf_funding_positioning_unwind_short": edge_mf_funding_positioning_unwind_short,
            "edge_mf_cross_asset_leadlag_long": edge_mf_cross_asset_leadlag_long,
            "edge_mf_cross_asset_leadlag_short": edge_mf_cross_asset_leadlag_short,
            "edge_mf_cross_asset_breakdown_long": edge_mf_cross_asset_breakdown_long,
            "edge_mf_cross_asset_breakdown_short": edge_mf_cross_asset_breakdown_short,
            "edge_mf_liquidity_regime_long": edge_mf_liquidity_regime_long,
            "edge_mf_liquidity_regime_short": edge_mf_liquidity_regime_short,
            "edge_mf_liquidity_meanrev_long": edge_mf_liquidity_meanrev_long,
            "edge_mf_liquidity_meanrev_short": edge_mf_liquidity_meanrev_short,
        }
        out: dict[str, pd.Series] = {}
        for k, v in masks.items():
            s = v if isinstance(v, pd.Series) else pd.Series(v, index=f.index)
            out[k] = s.fillna(False).astype(bool)
        return out

    @staticmethod
    def _event_cost_bps(event_name: str, frame: pd.DataFrame) -> pd.Series:
        idx = frame.index
        spread_proxy = pd.to_numeric(
            frame["spread_proxy_bps"] if "spread_proxy_bps" in frame.columns else pd.Series(0.0, index=idx),
            errors="coerce",
        ).fillna(0.0)
        latency = pd.to_numeric(
            frame["trade_time_since_shock_1m"] if "trade_time_since_shock_1m" in frame.columns else pd.Series(0.0, index=idx),
            errors="coerce",
        ).fillna(0.0)
        if event_name.startswith("edge_cross_venue_"):
            base = pd.Series(7.0, index=idx)
            return base + (spread_proxy * 0.20).clip(lower=0.0, upper=5.0) + (latency * 0.02).clip(lower=0.0, upper=3.0)
        if event_name.startswith("edge_liquidity_imbalance"):
            base = pd.Series(6.0, index=idx)
            return base + (spread_proxy * 0.15).clip(lower=0.0, upper=4.0)
        if event_name.startswith("edge_volatility_regime_break"):
            return pd.Series(5.5, index=idx) + (spread_proxy * 0.10).clip(lower=0.0, upper=3.0)
        if event_name.startswith("edge_funding_positioning_unwind"):
            return pd.Series(5.0, index=idx) + (spread_proxy * 0.08).clip(lower=0.0, upper=2.5)
        if event_name.startswith("edge_mf_cross_asset"):
            return pd.Series(5.8, index=idx) + (spread_proxy * 0.10).clip(lower=0.0, upper=3.0)
        if event_name.startswith("edge_mf_vol_transition"):
            return pd.Series(5.6, index=idx) + (spread_proxy * 0.10).clip(lower=0.0, upper=3.0)
        if event_name.startswith("edge_mf_funding_positioning"):
            return pd.Series(5.2, index=idx) + (spread_proxy * 0.08).clip(lower=0.0, upper=2.5)
        if event_name.startswith("edge_mf_liquidity"):
            return pd.Series(6.2, index=idx) + (spread_proxy * 0.14).clip(lower=0.0, upper=4.0)
        return pd.Series(5.0, index=idx)

    def _stats(self, x: pd.Series, min_samples: int) -> dict[str, float]:
        x = pd.to_numeric(x, errors="coerce").dropna()
        n = int(x.shape[0])
        if n < min_samples:
            return {
                "samples": float(n),
                "expectancy": 0.0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "t_stat": 0.0,
                "sharpe": 0.0,
                "std": 0.0,
                "lcb_expectancy": 0.0,
                "valid": 0.0,
            }

        wins = x[x > 0.0]
        losses = x[x < 0.0]
        expectancy = float(x.mean())
        std = self._safe_std(x)
        pf = float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else 10.0
        t_stat = float((expectancy / (std / np.sqrt(n))) if std > 1e-10 else 0.0)
        sharpe = float((expectancy / std) * np.sqrt(24.0 * 365.0)) if std > 1e-10 else 0.0
        lcb = float(expectancy - (self.config.confidence_z * (std / np.sqrt(n)))) if std > 1e-10 else expectancy
        valid = float(np.isfinite(expectancy) and np.isfinite(std) and std > 1e-12)

        return {
            "samples": float(n),
            "expectancy": expectancy,
            "win_rate": float((x > 0.0).mean()),
            "profit_factor": pf,
            "t_stat": t_stat,
            "sharpe": sharpe,
            "std": std,
            "lcb_expectancy": lcb,
            "valid": valid,
        }

    def _measure_event(
        self,
        f: pd.DataFrame,
        event_name: str,
        mask: pd.Series,
        min_samples: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        active = f[mask]
        event_liq_diag = self._liquidity_diagnostics(active)
        if active.empty:
            rejected.append({
                "event": event_name,
                "reason": ["no_event_triggers"],
                "liquidity_diagnostics": event_liq_diag,
            })
            return accepted, rejected

        family_min_samples = max(min_samples, 500)
        if active.shape[0] < family_min_samples:
            rejected.append({
                "event": event_name,
                "reason": ["insufficient_event_samples"],
                "samples": int(active.shape[0]),
                "liquidity_diagnostics": event_liq_diag,
            })
            return accepted, rejected

        for horizon in self.config.horizons:
            fwd = self._forward_returns(f["close"], horizon=horizon)
            seg = f.loc[mask, ["regime", "volatility_state", "session", "hour_bucket", "asset_correlation_state"]].copy()
            seg["fwd"] = fwd.loc[mask]
            seg["cost_bps"] = self._event_cost_bps(event_name, f.loc[mask])
            seg["hedge_fill_probability"] = pd.to_numeric(f.loc[mask].get("hedge_fill_probability", 1.0), errors="coerce").fillna(1.0)
            seg = seg.dropna()

            if seg.empty:
                rejected.append({
                    "event": event_name,
                    "horizon": horizon,
                    "reason": ["missing_forward_returns"],
                    "liquidity_diagnostics": event_liq_diag,
                })
                continue

            for direction, sign in (("long", 1.0), ("short", -1.0)):
                ret_dir = (seg["fwd"] * sign) - (seg["cost_bps"] / 10000.0)
                if event_name.startswith("edge_cross_venue_"):
                    ret_dir = ret_dir * seg["hedge_fill_probability"].clip(lower=0.05, upper=1.0)
                seg["ret_dir"] = ret_dir
                seg["ret_inv"] = -seg["ret_dir"]
                grouped = seg.groupby(["regime", "volatility_state", "session"], dropna=False)

                for (regime, vol_state, session), part in grouped:
                    stats = self._stats(part["ret_dir"], min_samples=self.config.min_segment_samples)
                    inv_stats = self._stats(part["ret_inv"], min_samples=self.config.min_segment_samples)
                    part_liq_diag = self._liquidity_diagnostics(active.loc[part.index])

                    reasons: list[str] = []
                    if int(stats["samples"]) < self.config.min_segment_samples:
                        reasons.append("insufficient_segment_samples")
                    if stats["valid"] < 0.5:
                        reasons.append("unstable_variance")
                    if stats["t_stat"] <= 1.5:
                        reasons.append("insufficient_significance")
                    if stats["lcb_expectancy"] <= 0.0:
                        reasons.append("non_positive_lower_confidence_bound")
                    if stats["expectancy"] <= inv_stats["expectancy"]:
                        reasons.append("no_directional_asymmetry")
                    if event_name.startswith("time_"):
                        reasons.append("time_overfit_risk")

                    mode_corr = part["asset_correlation_state"].mode().dropna()
                    corr_state = str(mode_corr.iloc[0]) if not mode_corr.empty else "neutral_corr"
                    payload = {
                        "event": event_name,
                        "horizon": int(horizon),
                        "direction": direction,
                        "conditions": {
                            "regime": str(regime),
                            "volatility_state": str(vol_state),
                            "session": str(session),
                        },
                        "stats": stats,
                        "inverted_stats": inv_stats,
                        "follow_through_score": float(stats.get("expectancy", 0.0)),
                        "reversal_score": float(inv_stats.get("expectancy", 0.0)),
                        "event_outcome": (
                            "true_breakout"
                            if float(stats.get("expectancy", 0.0)) > 0.0 and float(inv_stats.get("expectancy", 0.0)) <= 0.0
                            else "failed_breakout"
                        ),
                        "liquidity_diagnostics": part_liq_diag,
                        "context": {
                            "asset_correlation_state": corr_state,
                            "mean_cost_bps": float(pd.to_numeric(part["cost_bps"], errors="coerce").mean()),
                            "mean_hedge_fill_probability": float(pd.to_numeric(part["hedge_fill_probability"], errors="coerce").mean()),
                        },
                    }
                    if reasons:
                        payload["reason"] = reasons
                        rejected.append(payload)
                    else:
                        accepted.append(payload)

        return accepted, rejected

    @staticmethod
    def _liquidity_diagnostics(frame: pd.DataFrame) -> dict[str, float | bool]:
        if frame is None or frame.empty:
            return {
                "liquidity_present": False,
                "refill_observed": False,
                "impact_persistent": False,
            }

        def _mean_col(name: str) -> float:
            if name not in frame.columns:
                return 0.0
            return float(pd.to_numeric(frame[name], errors="coerce").fillna(0.0).mean())

        volume_presence = _mean_col("normalized_volume")
        vps_presence = _mean_col("trade_volume_per_second_5s")
        refill_signal = _mean_col("trade_absorption_5s")
        refill_seq = _mean_col("trade_sequence_burst_absorption_reversal")
        impact_signal = _mean_col("trade_impact_efficiency_5s")
        impact_response = abs(_mean_col("trade_event_a_response_score")) + abs(_mean_col("trade_event_b_response_score"))

        liquidity_present = (volume_presence > 0.1) or (vps_presence > 0.01)
        refill_observed = (refill_signal > 0.01) or (refill_seq > 0.01)
        impact_persistent = (abs(impact_signal) > 1e-4) or (impact_response > 1e-4)

        return {
            "liquidity_present": bool(liquidity_present),
            "refill_observed": bool(refill_observed),
            "impact_persistent": bool(impact_persistent),
        }

    def _oos_survival(self, train_edge: dict[str, Any], oos_frame: pd.DataFrame, event_mask: pd.Series) -> tuple[bool, dict[str, Any], list[str]]:
        horizon = int(train_edge["horizon"])
        direction = str(train_edge["direction"])
        sign = 1.0 if direction == "long" else -1.0

        cond = train_edge["conditions"]
        mask = (
            event_mask
            & (oos_frame["regime"] == cond["regime"])
            & (oos_frame["volatility_state"] == cond["volatility_state"])
            & (oos_frame["session"] == cond["session"])
        )

        fwd = self._forward_returns(oos_frame["close"], horizon)
        oos_ret = (fwd.loc[mask] * sign).dropna()
        oos_stats = self._stats(oos_ret, min_samples=max(self.config.min_oos_samples, int(self.config.min_segment_samples * 0.4)))

        reasons: list[str] = []
        train_exp = float(train_edge["stats"]["expectancy"])
        oos_exp = float(oos_stats["expectancy"])
        if int(oos_stats["samples"]) < self.config.min_oos_samples:
            reasons.append("oos_data_sparsity")
        if oos_exp <= 0.0:
            reasons.append("oos_expectancy_non_positive")
        if float(oos_stats.get("t_stat", 0.0)) < self.config.min_oos_t_stat:
            reasons.append("oos_weak_t_stat")
        if float(oos_stats.get("profit_factor", 0.0)) < self.config.min_oos_profit_factor:
            reasons.append("oos_weak_profit_factor")
        if np.sign(train_exp) != np.sign(oos_exp if oos_exp != 0 else train_exp):
            reasons.append("oos_sign_flip")
        if abs(oos_exp) < abs(train_exp) * 0.25:
            reasons.append("oos_expectancy_collapse")
        if float(oos_stats["std"]) > float(train_edge["stats"]["std"]) * 2.2:
            reasons.append("oos_variance_explosion")
        if float(oos_stats.get("profit_factor", 0.0)) > self.config.max_pf_sanity and int(oos_stats["samples"]) < 120:
            reasons.append("oos_profit_factor_anomaly")
        return len(reasons) == 0, oos_stats, reasons

    @staticmethod
    def _edge_family(edge: dict[str, Any]) -> str:
        event = str(edge.get("event", "unknown"))
        if event.startswith("edge_cross_venue_"):
            return "cross_venue_inefficiency"
        if event.startswith("edge_liquidity_imbalance"):
            return "liquidity_imbalance"
        if event.startswith("edge_volatility_regime_break"):
            return "volatility_regime_break"
        if event.startswith("edge_funding_positioning_unwind"):
            return "funding_positioning_pressure"
        if event.startswith("edge_mf_vol_transition"):
            return "mf_volatility_transition"
        if event.startswith("edge_mf_funding_positioning"):
            return "mf_funding_positioning"
        if event.startswith("edge_mf_cross_asset"):
            return "mf_cross_asset_leadlag"
        if event.startswith("edge_mf_liquidity"):
            return "mf_liquidity_regime"
        if event.startswith("positioning"):
            return "positioning"
        if event.startswith("flow"):
            return "flow"
        if event.startswith("liquidation"):
            return "liquidation"
        if event.startswith("vol"):
            return "volatility"
        if event.startswith("event"):
            return "event"
        if event.startswith("interaction"):
            return "interaction"
        if event.startswith("edge_"):
            return "execution_microstructure"
        if event.startswith("session"):
            return "session"
        return "other"

    def _portfolio_filter(self, edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        family_count: dict[str, int] = {}
        symbol_count: dict[str, int] = {}

        for edge in edges:
            family = self._edge_family(edge)
            assets = [str(x) for x in edge.get("assets", [])]
            if family_count.get(family, 0) >= 2:
                continue
            if any(symbol_count.get(asset, 0) >= 2 for asset in assets):
                continue

            correlated = False
            for chosen in selected:
                if self._edge_family(chosen) == family:
                    cond_a = chosen.get("conditions", {}) or {}
                    cond_b = edge.get("conditions", {}) or {}
                    same_surface = (
                        str(cond_a.get("regime", "")) == str(cond_b.get("regime", ""))
                        and str(cond_a.get("volatility_state", "")) == str(cond_b.get("volatility_state", ""))
                        and str(cond_a.get("session", "")) == str(cond_b.get("session", ""))
                    )
                    asset_overlap = len(set(chosen.get("assets", [])) & set(assets)) > 0
                    if same_surface and asset_overlap:
                        correlated = True
                        break
            if correlated:
                continue

            selected.append(edge)
            family_count[family] = family_count.get(family, 0) + 1
            for asset in assets:
                symbol_count[asset] = symbol_count.get(asset, 0) + 1

        return selected

    def discover(self, symbol_frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        symbol_frames = self._inject_cross_asset_context(symbol_frames)
        diagnostics: dict[str, Any] = {
            "symbols": {},
            "summary": {
                "no_event_triggers": 0,
                "negative_expectancy": 0,
                "data_sparsity": 0,
                "over_conditioning": 0,
            },
        }

        accepted_by_symbol: dict[str, list[dict[str, Any]]] = {}
        rejected_edges: list[dict[str, Any]] = []

        for symbol, raw_df in symbol_frames.items():
            f = self._prepare_frame(raw_df)
            if f.empty or len(f) < 300:
                rejected_edges.append({
                    "symbol": symbol,
                    "reason": ["data_sparsity"],
                })
                diagnostics["summary"]["data_sparsity"] += 1
                diagnostics["symbols"][symbol] = {"status": "insufficient_data", "rows": int(len(f))}
                continue

            split = int(len(f) * self.config.train_fraction)
            train_f = f.iloc[:split].copy()
            oos_f = f.iloc[split:].copy()
            if train_f.empty or oos_f.empty:
                rejected_edges.append({"symbol": symbol, "reason": ["invalid_oos_split"]})
                diagnostics["summary"]["data_sparsity"] += 1
                diagnostics["symbols"][symbol] = {"status": "invalid_oos_split"}
                continue

            event_masks_train = self._event_masks(train_f)
            event_masks_oos = self._event_masks(oos_f)
            symbol_accepted: list[dict[str, Any]] = []

            event_counts: dict[str, int] = {k: int(v.sum()) for k, v in event_masks_train.items()}
            diagnostics["symbols"][symbol] = {
                "event_counts": event_counts,
                "rows_train": int(len(train_f)),
                "rows_oos": int(len(oos_f)),
            }

            for event_name, mask_train in event_masks_train.items():
                accepted, rejected = self._measure_event(
                    train_f,
                    event_name=event_name,
                    mask=mask_train,
                    min_samples=self.config.min_event_samples,
                )

                for r in rejected:
                    row = {"symbol": symbol, **r}
                    rejected_edges.append(row)
                    reasons = set(r.get("reason", []))
                    if "no_event_triggers" in reasons:
                        diagnostics["summary"]["no_event_triggers"] += 1
                    if "insufficient_event_samples" in reasons or "insufficient_segment_samples" in reasons:
                        diagnostics["summary"]["data_sparsity"] += 1
                    if "non_positive_lower_confidence_bound" in reasons:
                        diagnostics["summary"]["negative_expectancy"] += 1
                    if "no_directional_asymmetry" in reasons:
                        diagnostics["summary"]["over_conditioning"] += 1

                oos_mask = event_masks_oos.get(event_name, pd.Series(False, index=oos_f.index))
                for a in accepted:
                    survives, oos_stats, oos_reasons = self._oos_survival(a, oos_f, oos_mask)
                    if not survives:
                        oos_liq_diag = self._liquidity_diagnostics(oos_f.loc[oos_mask])
                        rejected_edges.append({
                            "symbol": symbol,
                            **a,
                            "oos_stats": oos_stats,
                            "reason": oos_reasons,
                            "liquidity_diagnostics": oos_liq_diag,
                        })
                        if "oos_expectancy_non_positive" in oos_reasons or "oos_expectancy_collapse" in oos_reasons:
                            diagnostics["summary"]["negative_expectancy"] += 1
                        if "oos_data_sparsity" in oos_reasons:
                            diagnostics["summary"]["data_sparsity"] += 1
                        continue

                    edge_id = (
                        f"{event_name}|{a['conditions']['regime']}|{a['conditions']['volatility_state']}"
                        f"|{a['conditions']['session']}|h{int(a['horizon']):02d}|{a['direction']}"
                    )
                    symbol_accepted.append(
                        {
                            "edge_id": edge_id,
                            "event": event_name,
                            "symbol": symbol,
                            "direction": a["direction"],
                            "horizon": int(a["horizon"]),
                            "conditions": a["conditions"],
                            "stats": a["stats"],
                            "oos_stats": oos_stats,
                        }
                    )

            accepted_by_symbol[symbol] = symbol_accepted

        pooled: dict[str, list[dict[str, Any]]] = {}
        for symbol, edges in accepted_by_symbol.items():
            for e in edges:
                pooled.setdefault(e["edge_id"], []).append(e)

        generalized: list[dict[str, Any]] = []
        for edge_id, rows in pooled.items():
            assets = sorted({r["symbol"] for r in rows})
            if len(assets) < self.config.min_assets_required:
                rejected_edges.append(
                    {
                        "edge_id": edge_id,
                        "reason": ["fails_multi_asset_generalization"],
                        "assets": assets,
                    }
                )
                continue

            expectancy = float(np.mean([r["stats"]["expectancy"] for r in rows]))
            win_rate = float(np.mean([r["stats"]["win_rate"] for r in rows]))
            pf = float(np.mean([r["stats"]["profit_factor"] for r in rows]))
            t_stat = float(np.mean([r["stats"]["t_stat"] for r in rows]))
            sharpe = float(np.mean([r["stats"]["sharpe"] for r in rows]))
            lcb = float(np.mean([r["stats"]["lcb_expectancy"] for r in rows]))
            samples = int(sum(int(r["stats"]["samples"]) for r in rows))
            per_asset_expectancy = [float(r["stats"].get("expectancy", 0.0)) for r in rows]
            per_asset_pf = [float(r["stats"].get("profit_factor", 0.0)) for r in rows]
            exp_std = float(np.std(per_asset_expectancy)) if per_asset_expectancy else 0.0
            pf_std = float(np.std(per_asset_pf)) if per_asset_pf else 0.0
            stability_score = float(
                np.clip(
                    1.0 - min(1.0, (exp_std / max(abs(expectancy), 1e-9))),
                    0.0,
                    1.0,
                )
            )

            if samples < self.config.min_total_samples:
                rejected_edges.append(
                    {
                        "edge_id": edge_id,
                        "reason": ["insufficient_total_samples"],
                        "assets": assets,
                        "samples": samples,
                    }
                )
                continue

            if lcb <= 0.0:
                rejected_edges.append(
                    {
                        "edge_id": edge_id,
                        "reason": ["non_positive_lower_confidence_bound"],
                        "assets": assets,
                    }
                )
                diagnostics["summary"]["negative_expectancy"] += 1
                continue

            oos_pf = float(np.mean([r["oos_stats"]["profit_factor"] for r in rows]))
            oos_t = float(np.mean([r["oos_stats"]["t_stat"] for r in rows]))
            oos_exp = float(np.mean([r["oos_stats"]["expectancy"] for r in rows]))
            positive_oos_share = float(np.mean([1.0 if float(r["oos_stats"]["expectancy"]) > 0.0 else 0.0 for r in rows]))
            if oos_pf > self.config.max_pf_sanity and samples < 250:
                rejected_edges.append(
                    {
                        "edge_id": edge_id,
                        "reason": ["profit_factor_anomaly"],
                        "assets": assets,
                        "samples": samples,
                    }
                )
                continue
            if oos_exp <= 0.0 or oos_t < self.config.min_oos_t_stat or oos_pf < self.config.min_oos_profit_factor:
                rejected_edges.append(
                    {
                        "edge_id": edge_id,
                        "reason": ["fails_oos_statistical_gate"],
                        "assets": assets,
                        "oos_expectancy": oos_exp,
                        "oos_t_stat": oos_t,
                        "oos_profit_factor": oos_pf,
                    }
                )
                continue
            if positive_oos_share < 0.65:
                rejected_edges.append(
                    {
                        "edge_id": edge_id,
                        "reason": ["regime_dependent_collapse"],
                        "assets": assets,
                        "positive_oos_share": positive_oos_share,
                    }
                )
                continue

            representative = rows[0]
            confidence_score = float(np.clip((t_stat / 4.0) * max(0.0, lcb * 120.0), 0.0, 1.0))
            generalized.append(
                {
                    "edge_id": edge_id,
                    "event": representative["event"],
                    "event_definition": representative["event"],
                    "direction": representative["direction"],
                    "horizon": representative["horizon"],
                    "holding_period": int(representative["horizon"]),
                    "confidence_score": confidence_score,
                    "expected_return": expectancy,
                    "regime": representative["conditions"].get("regime", "unknown"),
                    "asset_coverage": assets,
                    "sample_size": float(samples),
                    "conditions": representative["conditions"],
                    "assets": assets,
                    "stats": {
                        "samples": float(samples),
                        "expectancy": expectancy,
                        "win_rate": win_rate,
                        "profit_factor": pf,
                        "t_stat": t_stat,
                        "sharpe": sharpe,
                        "lcb_expectancy": lcb,
                        "cross_asset_expectancy_std": exp_std,
                        "cross_asset_pf_std": pf_std,
                        "cross_asset_stability": stability_score,
                    },
                    "oos_stats": {
                        "expectancy": float(np.mean([r["oos_stats"]["expectancy"] for r in rows])),
                        "profit_factor": float(np.mean([r["oos_stats"]["profit_factor"] for r in rows])),
                        "t_stat": float(np.mean([r["oos_stats"]["t_stat"] for r in rows])),
                        "samples": float(np.mean([r["oos_stats"]["samples"] for r in rows])),
                    },
                    "in_sample_metrics": {
                        "samples": float(samples),
                        "expectancy": expectancy,
                        "win_rate": win_rate,
                        "profit_factor": pf,
                        "t_stat": t_stat,
                        "sharpe": sharpe,
                        "lcb_expectancy": lcb,
                    },
                    "out_of_sample_metrics": {
                        "expectancy": float(np.mean([r["oos_stats"]["expectancy"] for r in rows])),
                        "profit_factor": float(np.mean([r["oos_stats"]["profit_factor"] for r in rows])),
                        "t_stat": float(np.mean([r["oos_stats"]["t_stat"] for r in rows])),
                        "samples": float(np.mean([r["oos_stats"]["samples"] for r in rows])),
                    },
                    "decay_metrics": {
                        "rolling_expectancy": expectancy,
                        "rolling_pf": pf,
                        "rolling_t_stat": t_stat,
                        "samples": float(samples),
                    },
                }
            )

        generalized.sort(
            key=lambda x: (
                float(x["stats"]["lcb_expectancy"]),
                float(x["oos_stats"]["t_stat"]),
                float(x["stats"]["t_stat"]),
                float(x["stats"]["profit_factor"]),
            ),
            reverse=True,
        )
        generalized = self._portfolio_filter(generalized)

        registry_payload = {
            "active_version": EdgeRegistry.new_version(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "edges": [
                {
                    "edge_id": row["edge_id"],
                    "conditions": row["conditions"],
                    "event_definition": row["event_definition"],
                    "direction": row["direction"],
                    "confidence_score": row["confidence_score"],
                    "expected_return": row["expected_return"],
                    "holding_period": row["holding_period"],
                    "regime": row["regime"],
                    "asset_coverage": row["asset_coverage"],
                    "sample_size": row["sample_size"],
                    "in_sample_metrics": row["in_sample_metrics"],
                    "out_of_sample_metrics": row["out_of_sample_metrics"],
                    "decay_metrics": row["decay_metrics"],
                    "assets": row["assets"],
                    "stats": row["stats"],
                    "oos_stats": row["oos_stats"],
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "version": "pending_activation",
                    "active": True,
                    "state": "shadow",
                }
                for row in generalized
            ],
        }

        return {
            "edge_registry": registry_payload,
            "top_edges": generalized[: self.config.max_top_edges],
            "rejected_edges": rejected_edges,
            "diagnostics": diagnostics,
        }
