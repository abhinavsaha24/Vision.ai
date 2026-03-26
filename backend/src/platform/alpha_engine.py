from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.src.models.meta_alpha_engine import MetaAlphaEngine
from backend.src.models.regime_detector import MarketRegimeDetector
from backend.src.platform.edge_registry import EdgeRegistry
from backend.src.platform.flow_features import FlowFeatureEngineer


logger = logging.getLogger(__name__)


@dataclass
class EdgeStat:
    name: str
    trades: int
    expectancy: float
    win_rate: float
    profit_factor: float
    t_stat: float
    passed: bool
    selection: str = "strict"


@dataclass
class ConditionalEdge:
    condition: str
    event: str
    regime: str
    volatility_state: str
    session: str
    hour_bucket: int
    direction: str
    trades: int
    expectancy: float
    win_rate: float
    profit_factor: float
    t_stat: float


@dataclass
class RegistryRuntimeEdge:
    edge_id: str
    event: str
    regime: str
    volatility_state: str
    session: str
    direction: str
    stats: EdgeStat
    hour_bucket: int | None = None


class AlphaEngine:
    """Institutional alpha engine using vetted 1H/4H signals only."""

    def __init__(
        self,
        edge_min_win_rate: float = 0.50,
        edge_min_profit_factor: float = 1.05,
        edge_min_t_stat: float = 1.4,
        edge_min_expectancy: float = 0.0,
        fallback_top_k: int = 1,
        trend_entry_threshold: float = 0.16,
        range_entry_threshold: float = 0.13,
        min_confidence: float = 0.50,
        max_trades_24h: int = 5,
        min_hours_between_trades: int = 1,
        weak_tier_max_cap: float = 0.05,
        edge_registry_path: str | None = None,
    ):
        self.meta_alpha = MetaAlphaEngine(
            trend_entry_threshold=trend_entry_threshold,
            range_entry_threshold=range_entry_threshold,
            min_confidence=min_confidence,
        )
        self.regime_detector = MarketRegimeDetector()
        self._bars_1h: deque[dict[str, float | str]] = deque(maxlen=1200)
        self._current_hour: dict[str, float | str] | None = None
        self._edge_stats: dict[str, EdgeStat] = {}
        self._edge_registry: dict[str, ConditionalEdge] = {}
        self._edge_lifecycle = EdgeRegistry()
        self._runtime_registry: list[RegistryRuntimeEdge] = []
        self._last_live_edge: str | None = None
        self._last_live_edge_stat: EdgeStat | None = None
        self._registry_reload_interval_bars = 24
        self._bars_since_registry_reload = 0
        self.edge_registry_path = edge_registry_path or os.getenv("EDGE_REGISTRY_PATH", "data/edge_registry.json")
        self.edge_min_win_rate = edge_min_win_rate
        self.edge_min_profit_factor = edge_min_profit_factor
        self.edge_min_t_stat = edge_min_t_stat
        self.edge_min_expectancy = edge_min_expectancy
        self.fallback_top_k = fallback_top_k
        self._trade_timestamps: deque[datetime] = deque(maxlen=500)
        self.max_trades_24h = max(1, int(max_trades_24h))
        self.min_hours_between_trades = max(0, int(min_hours_between_trades))
        self.weak_tier_max_cap = float(np.clip(weak_tier_max_cap, 0.01, 0.08))
        self._load_registry_snapshot()

    def _load_registry_snapshot(self) -> None:
        path = Path(self.edge_registry_path)
        if not path.exists():
            self._edge_stats = {}
            self._runtime_registry = []
            self._edge_lifecycle.set_entries([])
            return

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("edge_registry_parse_failed path=%s err=%s", path, exc)
            payload = {}
        rows = payload.get("edges", []) if isinstance(payload, dict) else []
        runtime_registry: list[RegistryRuntimeEdge] = []
        edge_stats: dict[str, EdgeStat] = {}

        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("state", "active")) == "retired":
                continue
            if not bool(row.get("active", True)):
                continue

            edge_id = str(row.get("edge_id", "")).strip()
            if not edge_id:
                continue

            conditions = row.get("conditions", {}) or {}
            stats_raw = row.get("stats", {}) or {}
            stat = EdgeStat(
                name=edge_id,
                trades=int(float(stats_raw.get("samples", stats_raw.get("trades", 0)) or 0)),
                expectancy=float(stats_raw.get("expectancy", 0.0) or 0.0),
                win_rate=float(stats_raw.get("win_rate", 0.0) or 0.0),
                profit_factor=float(stats_raw.get("profit_factor", 0.0) or 0.0),
                t_stat=float(stats_raw.get("t_stat", 0.0) or 0.0),
                passed=True,
                selection="registry",
            )
            edge_stats[edge_id] = stat
            runtime_registry.append(
                RegistryRuntimeEdge(
                    edge_id=edge_id,
                    event=str(row.get("event", conditions.get("event", ""))),
                    regime=str(conditions.get("regime", row.get("regime", ""))),
                    volatility_state=str(conditions.get("volatility_state", "")),
                    session=str(conditions.get("session", "")),
                    direction=str(row.get("direction", "")),
                    hour_bucket=(
                        int(conditions["hour_bucket"])
                        if "hour_bucket" in conditions and conditions.get("hour_bucket") is not None
                        else None
                    ),
                    stats=stat,
                )
            )

        self._edge_stats = edge_stats
        self._runtime_registry = runtime_registry
        self._edge_lifecycle = EdgeRegistry.load(path)

    @staticmethod
    def _runtime_event_family(event: str) -> str:
        e = str(event)
        if e.startswith("funding"):
            return "funding_extremes"
        if e.startswith("oi"):
            return "oi_price_divergence"
        return "liquidation_events"

    def _registry_edge_matches(
        self,
        edge: RegistryRuntimeEdge,
        event: str,
        regime: str,
        volatility_state: str,
        session: str,
        hour_bucket: int,
        direction: str,
    ) -> bool:
        if edge.direction != direction:
            return False
        if edge.event != event:
            return False
        if edge.regime and edge.regime != regime:
            return False
        if edge.volatility_state and edge.volatility_state != volatility_state:
            return False
        if edge.session and edge.session != session:
            return False
        if edge.hour_bucket is not None and int(edge.hour_bucket) != int(hour_bucket):
            return False
        return True

    @staticmethod
    def _edge_quality_scalar(edge_stats: dict[str, EdgeStat]) -> float:
        if not edge_stats:
            return 0.5
        vals: list[float] = []
        for stat in edge_stats.values():
            if stat.trades < 20:
                continue
            q = (
                min(1.0, max(0.0, stat.expectancy * 500.0))
                + min(1.0, max(0.0, (stat.profit_factor - 1.0) / 1.2))
                + min(1.0, max(0.0, stat.t_stat / 3.0))
            ) / 3.0
            vals.append(q)
        if not vals:
            return 0.5
        return float(np.clip(np.mean(vals), 0.25, 1.0))

    @staticmethod
    def _setup_tier(score: float, confidence: float) -> str:
        strength = abs(score)
        if confidence >= 0.70 and strength >= 0.24:
            return "strong"
        if confidence >= 0.57 and strength >= 0.14:
            return "moderate"
        return "none"

    @staticmethod
    def _regime_bucket(regime_data: dict[str, Any]) -> str:
        if regime_data.get("market_state") == "VOLATILE" or regime_data.get("volatility") == "high_volatility":
            return "high_volatility"
        if regime_data.get("market_state") == "TREND":
            return "trend"
        return "range"

    def _passes_global_edge_filter(self, filtered_scores: dict[str, float]) -> bool:
        if self._last_live_edge_stat is not None:
            s = self._last_live_edge_stat
            return bool(s.expectancy > 0.0 and s.profit_factor > 1.2 and s.t_stat > 1.5 and s.trades > 50)

        active: list[tuple[float, EdgeStat]] = []
        for name, score in filtered_scores.items():
            if abs(float(score)) <= 1e-8:
                continue
            stat = self._edge_stats.get(name)
            if not stat:
                continue
            active.append((abs(float(score)), stat))

        if not active:
            return False

        total_w = sum(w for w, _ in active)
        if total_w <= 0:
            return False

        exp_w = sum(w * s.expectancy for w, s in active) / total_w
        tstat_w = sum(w * s.t_stat for w, s in active) / total_w
        pf_w = sum(w * s.profit_factor for w, s in active) / total_w
        if exp_w <= 0.0:
            return False
        if tstat_w < max(0.55, self.edge_min_t_stat * 0.45):
            return False
        if pf_w < 1.0:
            return False
        return True

    @staticmethod
    def _flow_confirmation(meta: dict[str, Any]) -> tuple[bool, str]:
        flow_alignment = str(meta.get("flow_alignment", "neutral"))
        flow_score = float(meta.get("flow_score", 0.0) or 0.0)
        structure_score = float(meta.get("structure_score", 0.0) or 0.0)
        decision = str(meta.get("decision", "none"))

        if abs(flow_score) < 0.10:
            return False, "flow_neutral"
        if flow_alignment != "aligned":
            return False, "flow_structure_conflict"
        if decision == "long" and flow_score <= 0:
            return False, "flow_direction_mismatch"
        if decision == "short" and flow_score >= 0:
            return False, "flow_direction_mismatch"
        if decision == "none":
            return False, "no_decision"
        if math.isclose(structure_score, 0.0, abs_tol=1e-8):
            return False, "missing_structure"
        return True, "confirmed"

    def _weighted_edge_expectancy(self, filtered_scores: dict[str, float]) -> float:
        if self._last_live_edge_stat is not None:
            return float(self._last_live_edge_stat.expectancy)

        weighted = []
        for name, score in filtered_scores.items():
            if abs(float(score)) <= 1e-8:
                continue
            stat = self._edge_stats.get(name)
            if not stat:
                continue
            weighted.append((abs(float(score)), float(stat.expectancy)))
        if not weighted:
            return 0.0
        denom = sum(w for w, _ in weighted)
        if denom <= 0:
            return 0.0
        return float(sum(w * x for w, x in weighted) / denom)

    def get_edge_registry(self, top_n: int = 50) -> list[dict[str, Any]]:
        active = []
        for edge in self._edge_lifecycle.entries.values():
            if self._edge_lifecycle.get_active_edge(edge.edge_id) is None:
                continue
            active.append(edge)
        active.sort(
            key=lambda e: (
                float(e.stats.get("expectancy", 0.0)),
                float(e.stats.get("t_stat", 0.0)),
                float(e.stats.get("profit_factor", 0.0)),
            ),
            reverse=True,
        )
        return [
            {
                "condition": e.edge_id,
                "event": str(e.conditions.get("event", "")),
                "regime": str(e.conditions.get("regime", "")),
                "volatility_state": str(e.conditions.get("volatility_state", "")),
                "session": str(e.conditions.get("session", "")),
                "hour_bucket": int(e.conditions.get("hour_bucket", 0)),
                "direction": e.direction,
                "trades": int(e.stats.get("trades", 0)),
                "expectancy": float(e.stats.get("expectancy", 0.0)),
                "win_rate": float(e.stats.get("win_rate", 0.0)),
                "profit_factor": float(e.stats.get("profit_factor", 0.0)),
                "t_stat": float(e.stats.get("t_stat", 0.0)),
                "active": bool(e.active),
                "version": e.version,
            }
            for e in active[: max(1, int(top_n))]
        ]

    def _allow_trade_now(self, ts: datetime) -> bool:
        cutoff = ts - timedelta(hours=24)
        while self._trade_timestamps and self._trade_timestamps[0] < cutoff:
            self._trade_timestamps.popleft()

        if len(self._trade_timestamps) >= self.max_trades_24h:
            return False

        if self._trade_timestamps:
            delta = ts - self._trade_timestamps[-1]
            if delta.total_seconds() < (self.min_hours_between_trades * 3600):
                return False

        return True

    @staticmethod
    def _reward_multiple(setup_tier: str, score: float, confidence: float) -> float:
        strength = abs(score)
        if setup_tier == "strong" and confidence >= 0.72 and strength >= 0.30:
            return 4.0
        if setup_tier in {"strong", "moderate"} and confidence >= 0.56 and strength >= 0.16:
            return 3.0
        return 2.0

    @staticmethod
    def _execution_refinement_score(last_bar: pd.Series) -> float:
        high = float(last_bar["high"])
        low = float(last_bar["low"])
        close = float(last_bar["close"])
        open_ = float(last_bar["open"])
        rng = max(high - low, 1e-9)
        close_location = (close - low) / rng
        body_ratio = abs(close - open_) / rng
        quality = 0.5 + ((body_ratio - 0.3) * 0.6)
        quality += (close_location - 0.5) * 0.2
        return float(np.clip(quality, 0.2, 1.2))

    def _four_hour_bias(self, df4h: pd.DataFrame) -> float:
        f4 = self._feature_frame(df4h)
        if len(f4) < 30:
            return 0.0
        last = f4.iloc[-1]
        trend = float(np.sign(last["close"] - last["close_sma_20"]))
        structure = float(last["bos_up"] - last["bos_down"])
        flow = float(np.clip(last["delta_vol_z"] / 2.5, -1.0, 1.0))
        return float(np.clip((trend * 0.35) + (structure * 0.40) + (flow * 0.25), -1.0, 1.0))

    @staticmethod
    def _hour_floor(ts: datetime) -> datetime:
        return ts.replace(minute=0, second=0, microsecond=0)

    @staticmethod
    def _to_dt(value: str | datetime | None) -> datetime:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str) and value:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            dt = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def _context_keys() -> tuple[str, ...]:
        return (
            "open_interest",
            "open_interest_value",
            "funding_rate",
            "long_short_ratio",
            "long_account",
            "short_account",
            "liquidation_long_usd",
            "liquidation_short_usd",
            "session_asia",
            "session_eu",
            "session_us",
            "is_weekend",
            "hour_sin",
            "hour_cos",
            "vwap_24h",
            "value_area_distance",
            "realized_vol_12h",
            "vol_cluster_score",
        )

    def _context_payload(self, tick: dict[str, Any]) -> dict[str, float]:
        out: dict[str, float] = {}
        for key in self._context_keys():
            if key in tick:
                out[key] = float(tick.get(key, 0.0) or 0.0)
        return out

    def on_tick(self, tick: dict[str, Any], strategy_name: str = "default") -> dict[str, Any] | None:
        symbol = str(tick.get("symbol", "") or "").strip()
        if not symbol:
            logger.warning("alpha_engine_invalid_tick missing_symbol")
            return None

        ts = self._to_dt(tick.get("ts"))
        hour = self._hour_floor(ts)
        try:
            price = float(tick.get("price", 0.0) or 0.0)
        except (TypeError, ValueError):
            logger.warning("alpha_engine_invalid_tick invalid_price symbol=%s", symbol)
            return None
        if price <= 0.0:
            logger.warning("alpha_engine_invalid_tick non_positive_price symbol=%s", symbol)
            return None
        volume = float(tick.get("volume", 0.0) or 0.0)

        if self._current_hour is None:
            self._current_hour = {
                "ts": hour.isoformat(),
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": volume,
            }
            self._current_hour.update(self._context_payload(tick))
            return None

        current_hour = self._to_dt(str(self._current_hour["ts"]))
        if hour == current_hour:
            self._current_hour["high"] = max(float(self._current_hour["high"]), price)
            self._current_hour["low"] = min(float(self._current_hour["low"]), price)
            self._current_hour["close"] = price
            self._current_hour["volume"] = float(self._current_hour["volume"]) + volume
            for key, value in self._context_payload(tick).items():
                self._current_hour[key] = value
            return None

        closed = dict(self._current_hour)
        self._bars_1h.append(closed)
        self._current_hour = {
            "ts": hour.isoformat(),
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": volume,
        }
        self._current_hour.update(self._context_payload(tick))

        if len(self._bars_1h) < 140:
            return None

        df1h = self._bars_to_frame(list(self._bars_1h))
        df4h = self._resample_4h(df1h)

        if len(df4h) < 60:
            return None

        self._bars_since_registry_reload += 1
        if self._bars_since_registry_reload >= self._registry_reload_interval_bars:
            self._load_registry_snapshot()
            self._bars_since_registry_reload = 0

        if not self._runtime_registry:
            return None

        signal_scores = self._compute_signal_scores(df1h, df4h)

        if self._last_live_edge is None:
            return None

        filtered_scores: dict[str, float] = dict(signal_scores)

        regime_data = self.regime_detector.get_regime(df1h)
        regime = "trend" if regime_data.get("market_state") == "TREND" else "range"
        regime_bucket = self._regime_bucket(regime_data)

        if not self._passes_global_edge_filter(filtered_scores):
            return None

        meta = self.meta_alpha.combine(
            signal_scores=filtered_scores,
            regime=regime,
            edge_stats={k: v.__dict__ for k, v in self._edge_stats.items()},
        )

        side = meta["decision"]
        setup_tier = self._setup_tier(float(meta["score"]), float(meta["confidence"]))
        signal_expectancy = self._weighted_edge_expectancy(filtered_scores)

        if side == "none" or setup_tier == "none":
            return None

        # Hard flow gate: no trades when flow and structure do not agree.
        flow_ok, flow_reason = self._flow_confirmation(meta)
        if not flow_ok:
            return None

        # Global statistical veto: never enter with non-positive weighted expectancy.
        if signal_expectancy <= max(0.0, self.edge_min_expectancy):
            return None

        trade_ts = self._to_dt(str(closed["ts"]))
        if not self._allow_trade_now(trade_ts):
            return None

        sizing = self._position_sizing(
            df1h=df1h,
            meta=meta,
            setup_tier=setup_tier,
            edge_quality=self._edge_quality_scalar(self._edge_stats),
            regime_bucket=regime_bucket,
            flow_confirmed=flow_ok,
        )
        # Lower-timeframe execution refinement proxy from the just-closed 1H candle.
        execution_quality = self._execution_refinement_score(df1h.iloc[-1])
        sizing["position_fraction"] = float(np.clip(sizing["position_fraction"] * execution_quality, 0.0, 0.20))
        if sizing["position_fraction"] <= 0:
            return None

        last = df1h.iloc[-1]
        stop_distance = sizing["stop_distance"]
        rr_multiple = self._reward_multiple(setup_tier, float(meta["score"]), float(meta["confidence"]))
        if side == "long":
            stop_loss = float(last["close"] - stop_distance)
            take_profit = float(last["close"] + (rr_multiple * stop_distance))
            direction = "buy"
        else:
            stop_loss = float(last["close"] + stop_distance)
            take_profit = float(last["close"] - (rr_multiple * stop_distance))
            direction = "sell"

        self._trade_timestamps.append(trade_ts)

        return {
            "strategy_name": strategy_name,
            "symbol": symbol,
            "side": direction,
            "price": float(last["close"]),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "position_fraction": sizing["position_fraction"],
            "regime": regime,
            "regime_bucket": regime_bucket,
            "score": float(meta["score"]),
            "confidence": float(meta["confidence"]),
            "setup_tier": setup_tier,
            "rr_multiple": rr_multiple,
            "edge_expectancy": signal_expectancy,
            "execution_quality": execution_quality,
            "flow_confirmation": flow_reason,
            "light_exposure": False,
            "meta": meta,
            "signals": filtered_scores,
            "selected_edge": self._last_live_edge,
            "edge_registry_size": len(self._runtime_registry),
            "edge_stats": {k: v.__dict__ for k, v in self._edge_stats.items()},
            "timeframe": "1H/4H",
            "ts": closed["ts"],
        }

    @staticmethod
    def _bars_to_frame(bars: list[dict[str, float | str]]) -> pd.DataFrame:
        df = pd.DataFrame(bars)
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.set_index("ts").sort_index()
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        for col in ("open", "high", "low", "close", "volume"):
            if col not in df.columns:
                df[col] = 0.0
        return df

    @staticmethod
    def _resample_4h(df1h: pd.DataFrame) -> pd.DataFrame:
        return df1h.resample("4h").agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        ).dropna()

    @staticmethod
    def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
        tr = pd.concat(
            [
                (df["high"] - df["low"]).abs(),
                (df["high"] - df["close"].shift(1)).abs(),
                (df["low"] - df["close"].shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return tr.rolling(n).mean()

    def _feature_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["ret1"] = out["close"].pct_change().fillna(0.0)
        out["ret4"] = out["close"].pct_change(4).fillna(0.0)
        out["close_sma_20"] = out["close"].rolling(20).mean().bfill()
        out["atr"] = self._atr(out, 14)
        out["atr_long"] = self._atr(out, 50)

        out["delta_vol"] = np.sign(out["close"].diff().fillna(0.0)) * out["volume"]
        vol_std = out["delta_vol"].rolling(50).std().replace(0, np.nan)
        out["delta_vol_z"] = ((out["delta_vol"] - out["delta_vol"].rolling(50).mean()) / vol_std)
        out["delta_vol_z"] = out["delta_vol_z"].replace([np.inf, -np.inf], np.nan).fillna(0.0)

        hl_range = (out["high"] - out["low"]).replace(0, np.nan)
        out["order_book_imbalance_proxy"] = ((out["close"] - out["low"]) - (out["high"] - out["close"])) / hl_range
        out["order_book_imbalance_proxy"] = out["order_book_imbalance_proxy"].replace([np.inf, -np.inf], np.nan).fillna(0.0)

        out["swing_high_20"] = out["high"].rolling(20).max().shift(1)
        out["swing_low_20"] = out["low"].rolling(20).min().shift(1)

        wick_down = (out[["open", "close"]].min(axis=1) - out["low"]).clip(lower=0)
        wick_up = (out["high"] - out[["open", "close"]].max(axis=1)).clip(lower=0)
        out["wick_down_ratio"] = (wick_down / hl_range).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        out["wick_up_ratio"] = (wick_up / hl_range).replace([np.inf, -np.inf], np.nan).fillna(0.0)

        out["sweep_low"] = (out["low"] < out["swing_low_20"]) & (out["close"] > out["swing_low_20"])
        out["sweep_high"] = (out["high"] > out["swing_high_20"]) & (out["close"] < out["swing_high_20"])

        out["bos_up"] = (out["close"] > out["swing_high_20"]).astype(float)
        out["bos_down"] = (out["close"] < out["swing_low_20"]).astype(float)
        out["fake_break_up"] = ((out["high"] > out["swing_high_20"]) & (out["close"] <= out["swing_high_20"])).astype(float)
        out["fake_break_down"] = ((out["low"] < out["swing_low_20"]) & (out["close"] >= out["swing_low_20"])).astype(float)

        pressure = (out["close"] - out["close_sma_20"]) / out["atr"].replace(0, np.nan)
        out["trend_pressure"] = pressure.apply(np.tanh).fillna(0.0)

        # Context fields from market positioning feed.
        for key in self._context_keys():
            if key not in out.columns:
                out[key] = 0.0

        out["open_interest"] = pd.to_numeric(out["open_interest"], errors="coerce").fillna(0.0)
        out["funding_rate"] = pd.to_numeric(out["funding_rate"], errors="coerce").fillna(0.0)
        out["long_short_ratio"] = pd.to_numeric(out["long_short_ratio"], errors="coerce").replace(0.0, np.nan).fillna(1.0)
        out["liquidation_long_usd"] = pd.to_numeric(out["liquidation_long_usd"], errors="coerce").fillna(0.0)
        out["liquidation_short_usd"] = pd.to_numeric(out["liquidation_short_usd"], errors="coerce").fillna(0.0)
        out["value_area_distance"] = pd.to_numeric(out["value_area_distance"], errors="coerce").fillna(0.0)
        out["vol_cluster_score"] = pd.to_numeric(out["vol_cluster_score"], errors="coerce").fillna(1.0)

        out = FlowFeatureEngineer.enrich(out)

        lsr_std = out["long_short_ratio"].rolling(96).std().replace(0, np.nan)
        out["lsr_z"] = ((out["long_short_ratio"] - out["long_short_ratio"].rolling(96).mean()) / lsr_std).replace([np.inf, -np.inf], np.nan).fillna(0.0)

        atr_ratio = (out["atr"] / out["atr_long"].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
        out["atr_ratio"] = atr_ratio.fillna(1.0)
        out["vol_transition"] = out["atr_ratio"].diff(4).fillna(0.0)

        out["compression"] = (out["atr_ratio"] < 0.88).astype(float)
        out["expansion"] = (out["atr_ratio"] > 1.15).astype(float)
        return out.fillna(0.0)

    def _context_frame(self, f1: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=f1.index)
        out["regime"] = np.where(
            f1["atr_ratio"] > 1.25,
            "high_volatility",
            np.where(f1["trend_pressure"].abs() > 0.30, "trend", "range"),
        )
        out["volatility_state"] = np.where(f1["atr_ratio"] < 0.92, "compression", "expansion")
        out["session"] = np.where(
            f1.get("session_us", 0.0) > 0.5,
            "us",
            np.where(f1.get("session_eu", 0.0) > 0.5, "eu", "asia"),
        )
        out["hour_bucket"] = pd.DatetimeIndex(f1.index).hour.astype(int)
        return out

    def _flow_event_frame(self, f1: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=f1.index)
        out["funding_high"] = (f1["funding_z"] > 1.0).astype(float)
        out["funding_low"] = (f1["funding_z"] < -1.0).astype(float)
        out["oi_rise"] = (f1["oi_delta_z"] > 1.0).astype(float)
        out["oi_drop"] = (f1["oi_delta_z"] < -1.0).astype(float)
        out["liquidation_short_spike"] = (
            (f1["liquidation_z"] > 1.0) & (f1["liquidation_imbalance"] > 0.25)
        ).astype(float)
        out["liquidation_long_spike"] = (
            (f1["liquidation_z"] > 1.0) & (f1["liquidation_imbalance"] < -0.25)
        ).astype(float)
        return out

    @staticmethod
    def _edge_condition_name(
        event: str,
        regime: str,
        volatility_state: str,
        session: str,
        hour_bucket: int,
        direction: str,
    ) -> str:
        return f"{event}|{regime}|{volatility_state}|{session}|h{int(hour_bucket):02d}|{direction}"

    def _compute_signal_scores(self, df1h: pd.DataFrame, df4h: pd.DataFrame) -> dict[str, float]:
        f1 = self._feature_frame(df1h)
        ctx = self._context_frame(f1)
        events = self._flow_event_frame(f1)

        last_idx = f1.index[-1]
        c = ctx.loc[last_idx]
        event_scores: dict[str, list[float]] = {
            "funding_extremes": [],
            "oi_price_divergence": [],
            "liquidation_events": [],
        }
        selected: list[tuple[str, float]] = []

        for event in events.columns:
            event_value = pd.to_numeric(pd.Series([events.at[last_idx, event]]), errors="coerce").iloc[0]
            if float(event_value) <= 0.0:
                continue
            for direction in ("long", "short"):
                condition = self._edge_condition_name(
                    event=event,
                    regime=str(c["regime"]),
                    volatility_state=str(c["volatility_state"]),
                    session=str(c["session"]),
                    hour_bucket=int(c["hour_bucket"]),
                    direction=direction,
                )
                matched_edges = [
                    edge for edge in self._runtime_registry
                    if self._registry_edge_matches(
                        edge=edge,
                        event=event,
                        regime=str(c["regime"]),
                        volatility_state=str(c["volatility_state"]),
                        session=str(c["session"]),
                        hour_bucket=int(c["hour_bucket"]),
                        direction=direction,
                    )
                ]
                if not matched_edges:
                    continue

                matched_edges.sort(
                    key=lambda e: (
                        float(e.stats.expectancy),
                        float(e.stats.t_stat),
                        float(e.stats.profit_factor),
                    ),
                    reverse=True,
                )
                best_edge = matched_edges[0]
                stat = best_edge.stats

                sign = 1.0 if direction == "long" else -1.0
                quality = float(
                    np.clip(
                        (stat.expectancy * 3000.0)
                        + ((stat.profit_factor - 1.0) * 0.6)
                        + (stat.t_stat / 4.0),
                        0.0,
                        1.2,
                    )
                )
                signed_quality = sign * quality
                if event.startswith("funding"):
                    event_scores["funding_extremes"].append(signed_quality)
                elif event.startswith("oi"):
                    event_scores["oi_price_divergence"].append(signed_quality)
                else:
                    event_scores["liquidation_events"].append(signed_quality)
                selected.append((best_edge.edge_id, signed_quality))

        self._last_live_edge = None
        self._last_live_edge_stat = None
        if selected:
            selected.sort(key=lambda x: abs(float(x[1])), reverse=True)
            candidate = selected[0][0]
            active_edge = self._edge_lifecycle.get_active_edge(candidate)
            if active_edge is not None:
                self._last_live_edge = candidate
                self._last_live_edge_stat = self._edge_stats.get(self._last_live_edge)

        flow_vals = [x for vals in event_scores.values() for x in vals]
        flow_score = float(np.mean(flow_vals)) if flow_vals else 0.0
        last1 = f1.iloc[-1]
        structure_score = float(np.clip((last1["trend_pressure"] * 0.7) + (np.sign(last1["ret4"]) * 0.3), -1.0, 1.0))
        vol_score = float(np.clip(np.tanh(last1["vol_transition"] * 3.0), -1.0, 1.0))

        return {
            "price_structure": structure_score,
            "positioning_breakout": structure_score * 0.8,
            "funding_extremes": float(np.mean(event_scores["funding_extremes"])) if event_scores["funding_extremes"] else 0.0,
            "oi_price_divergence": float(np.mean(event_scores["oi_price_divergence"])) if event_scores["oi_price_divergence"] else 0.0,
            "liquidation_events": float(np.mean(event_scores["liquidation_events"])) if event_scores["liquidation_events"] else 0.0,
            "volatility_transition": vol_score,
            "flow_context_edge": flow_score,
        }

    def discover_edges(self, df1h: pd.DataFrame, df4h: pd.DataFrame) -> dict[str, EdgeStat]:
        # Runtime path is registry-only. This method is kept for backward compatibility.
        self._load_registry_snapshot()
        return dict(self._edge_stats)

    def _position_sizing(
        self,
        df1h: pd.DataFrame,
        meta: dict[str, Any],
        setup_tier: str,
        edge_quality: float,
        regime_bucket: str,
        flow_confirmed: bool,
    ) -> dict[str, float]:
        f1 = self._feature_frame(df1h)
        returns = f1["ret1"].iloc[-72:]
        vol = float(returns.std())

        confidence = float(meta["confidence"])
        score = float(meta["score"])
        p = 0.5 + (abs(score) * 0.35)
        payoff_ratio = 1.6
        kelly = max(0.0, p - (1 - p) / payoff_ratio)
        kelly_cap = 0.15
        kelly_frac = min(kelly, kelly_cap)

        target_bar_vol = 0.004
        vol_scalar = 1.0
        if vol > 1e-6:
            vol_scalar = float(np.clip(target_bar_vol / vol, 0.2, 1.2))

        strength = float(np.clip(abs(score) / 0.45, 0.10, 1.0))
        edge_scalar = float(np.clip(0.65 + (edge_quality * 0.70), 0.45, 1.25))
        flow_score = float(meta.get("flow_score", 0.0) or 0.0)
        structure_score = float(meta.get("structure_score", 0.0) or 0.0)
        aligned = float(np.sign(flow_score) == np.sign(structure_score) and abs(flow_score) > 0.10)
        alignment_strength = float(np.clip(abs(flow_score), 0.0, 1.0))
        alignment_scalar = 0.0 if not flow_confirmed else float(np.clip(0.55 + (alignment_strength * 0.95), 0.45, 1.40))
        raw_fraction = float(kelly_frac * vol_scalar * confidence * strength * edge_scalar * alignment_scalar * aligned)

        tier_limits = {
            "strong": (0.035, 0.20),
            "moderate": (0.010, 0.10),
            "weak": (0.004, self.weak_tier_max_cap),
            "none": (0.0, 0.0),
        }
        floor, cap = tier_limits.get(setup_tier, (0.0, 0.0))
        regime_cap_mult = {
            "trend": 1.00,
            "range": 0.55,
            "high_volatility": 0.70,
        }.get(regime_bucket, 0.50)
        cap *= regime_cap_mult

        if cap <= 0:
            position_fraction = 0.0
        else:
            position_fraction = float(np.clip(max(raw_fraction, floor), 0.0, cap))

        atr = float(f1["atr"].iloc[-1])
        stop_distance = max(atr * 1.8, float(df1h["close"].iloc[-1]) * 0.004)

        return {
            "position_fraction": position_fraction,
            "stop_distance": stop_distance,
        }
