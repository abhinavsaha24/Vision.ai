from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
import math


@dataclass
class TradeObservation:
    timestamp: str
    symbol: str
    edge_id: str
    pnl: float


@dataclass
class ShadowTrackerState:
    observations: list[TradeObservation] = field(default_factory=list)


class ShadowLiveTracker:
    """Tracks paper/live-shadow quality and per-edge decay diagnostics."""

    def __init__(self, window_days: int = 14, initial_equity: float = 1.0):
        self.window_days = max(7, int(window_days))
        self.initial_equity = max(float(initial_equity), 1e-9)
        self.state = ShadowTrackerState()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _profit_factor(xs: list[float]) -> float:
        wins = [x for x in xs if x > 0.0]
        losses = [x for x in xs if x < 0.0]
        gross_profit = float(sum(wins))
        gross_loss = float(abs(sum(losses)))
        if gross_loss <= 1e-12:
            return 10.0
        return float(gross_profit / gross_loss)

    @staticmethod
    def _sharpe(xs: list[float], trading_days_per_year: float = 365.0) -> float:
        if len(xs) < 2:
            return 0.0
        mean = float(sum(xs) / len(xs))
        variance = float(sum((x - mean) ** 2 for x in xs) / max(1, len(xs) - 1))
        std = math.sqrt(max(variance, 0.0))
        if std <= 1e-12:
            return 0.0
        return float((mean / std) * math.sqrt(max(1.0, float(trading_days_per_year))))

    def add_trade(self, symbol: str, edge_id: str, pnl: float, timestamp: str | None = None) -> None:
        ts = timestamp or self._now_iso()
        self.state.observations.append(
            TradeObservation(timestamp=ts, symbol=symbol, edge_id=edge_id or "unknown", pnl=float(pnl))
        )
        if len(self.state.observations) > 20000:
            self.state.observations = self.state.observations[-20000:]

    def snapshot(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=self.window_days)

        filtered_observations: list[TradeObservation] = []
        for obs in self.state.observations:
            try:
                obs_ts = datetime.fromisoformat(str(obs.timestamp).replace("Z", "+00:00"))
                if obs_ts.tzinfo is None:
                    obs_ts = obs_ts.replace(tzinfo=timezone.utc)
                obs_ts = obs_ts.astimezone(timezone.utc)
            except Exception:
                continue
            if obs_ts >= cutoff:
                filtered_observations.append(obs)

        xs = [float(o.pnl) for o in filtered_observations]
        if not xs:
            return {
                "rolling_window_pf": 0.0,
                "rolling_window_sharpe": 0.0,
                "max_drawdown": 0.0,
                "trade_count": 0,
                "window_days": int(self.window_days),
                "per_edge": {},
            }

        equity = []
        running = 1.0
        for pnl in xs:
            return_pct = float(pnl) / self.initial_equity
            running *= (1.0 + return_pct)
            equity.append(running)
        peak = 1.0
        max_dd = 0.0
        for e in equity:
            peak = max(peak, e)
            dd = 1.0 - (e / max(peak, 1e-12))
            max_dd = max(max_dd, dd)

        per_edge: dict[str, dict[str, Any]] = {}
        for obs in filtered_observations:
            bucket = per_edge.setdefault(obs.edge_id, {"trades": 0.0, "pnl_sum": 0.0, "returns": []})
            bucket["trades"] += 1.0
            bucket["pnl_sum"] += float(obs.pnl)
            bucket["returns"].append(float(obs.pnl))

        edge_report: dict[str, Any] = {}
        for edge_id, b in per_edge.items():
            returns = [float(x) for x in b.get("returns", [])]
            edge_report[edge_id] = {
                "trades": int(b["trades"]),
                "expectancy": float(sum(returns) / max(1, len(returns))),
                "profit_factor": self._profit_factor(returns),
                "sharpe": self._sharpe(returns),
                "pnl_sum": float(b["pnl_sum"]),
            }

        return {
            "rolling_window_pf": self._profit_factor(xs),
            "rolling_window_sharpe": self._sharpe(xs),
            "max_drawdown": float(max_dd),
            "trade_count": len(xs),
            "window_days": int(self.window_days),
            "per_edge": edge_report,
        }
