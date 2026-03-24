from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import math
import statistics
import dataclasses


@dataclass
class EdgeEntry:
    edge_id: str
    event_definition: str = ""
    direction: str = ""
    confidence_score: float = 0.0
    expected_return: float = 0.0
    holding_period: int = 4
    regime: str = "unknown"
    asset_coverage: list[str] = field(default_factory=list)
    sample_size: float = 0.0
    in_sample_metrics: dict[str, float] = field(default_factory=dict)
    out_of_sample_metrics: dict[str, float] = field(default_factory=dict)
    decay_metrics: dict[str, float] = field(default_factory=dict)
    conditions: dict[str, Any] = field(default_factory=dict)
    assets: list[str] = field(default_factory=list)
    stats: dict[str, float] = field(default_factory=dict)
    created_at: str = ""
    version: str = "pending_activation"
    active: bool = True
    state: str = "active"
    decay: dict[str, float] = field(default_factory=lambda: {
        "rolling_expectancy": 0.0,
        "rolling_pf": 0.0,
        "rolling_t_stat": 0.0,
        "samples": 0.0,
    })
    pnl_window: list[float] = field(default_factory=list)


class EdgeRegistry:
    def __init__(self):
        self.entries: dict[str, EdgeEntry] = {}
        self.active_version: str | None = None

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def new_version() -> str:
        return datetime.now(timezone.utc).strftime("v%Y%m%d%H%M%S")

    def set_entries(self, entries: list[EdgeEntry], version: str | None = None) -> None:
        self.entries = {e.edge_id: e for e in entries}
        self.active_version = version or self.new_version()
        for e in self.entries.values():
            e.version = self.active_version
            e.active = (e.state == "active")

    def activate_version(self, version: str) -> None:
        self.active_version = version
        for e in self.entries.values():
            e.active = (e.version == version and e.state == "active")

    def deactivate_edge(self, edge_id: str) -> None:
        if edge_id in self.entries:
            self.entries[edge_id].active = False
            self.entries[edge_id].state = "shadow"

    def retire_edge(self, edge_id: str) -> None:
        if edge_id in self.entries:
            self.entries[edge_id].active = False
            self.entries[edge_id].state = "retired"

    def activate_edge(self, edge_id: str) -> None:
        if edge_id in self.entries:
            self.entries[edge_id].active = True
            self.entries[edge_id].state = "active"

    def get_active_edge(self, edge_id: str) -> EdgeEntry | None:
        edge = self.entries.get(edge_id)
        if edge is None:
            return None
        if not edge.active:
            return None
        if edge.state != "active":
            return None
        if self.active_version is not None and edge.version != self.active_version:
            return None
        return edge

    @staticmethod
    def _mean(xs: list[float]) -> float:
        return float(sum(xs) / max(1, len(xs)))

    @staticmethod
    def _std(xs: list[float]) -> float:
        if len(xs) < 2:
            return 0.0
        return float(statistics.stdev(xs))

    @classmethod
    def _t_stat(cls, xs: list[float]) -> float:
        n = len(xs)
        if n < 2:
            return 0.0
        mu = cls._mean(xs)
        std = cls._std(xs)
        if std <= 1e-12:
            return 0.0
        return float(mu / (std / math.sqrt(n)))

    @staticmethod
    def _profit_factor(xs: list[float]) -> float:
        wins = [x for x in xs if x > 0]
        losses = [x for x in xs if x < 0]
        gross_profit = float(sum(wins))
        gross_loss = float(abs(sum(losses)))
        if gross_loss <= 1e-12:
            return 10.0
        return float(gross_profit / gross_loss)

    @staticmethod
    def _edge_anomalous(edge: EdgeEntry) -> bool:
        sample_size = float(edge.sample_size or edge.stats.get("samples", 0.0))
        pf = float(edge.out_of_sample_metrics.get("profit_factor", 0.0))
        if sample_size < 60:
            return True
        if pf > 10.0 and sample_size < 250:
            return True
        return False

    def update_decay(self, edge_id: str, pnl: float) -> None:
        edge = self.entries.get(edge_id)
        if edge is None:
            return
        edge.pnl_window.append(float(pnl))
        if len(edge.pnl_window) > 200:
            edge.pnl_window = edge.pnl_window[-200:]

        window = edge.pnl_window[-80:]
        n = len(window)
        expectancy = self._mean(window)
        pf = self._profit_factor(window)
        t_stat = self._t_stat(window)

        d = edge.decay
        d["rolling_expectancy"] = expectancy
        d["rolling_pf"] = pf
        d["rolling_t_stat"] = t_stat
        d["samples"] = float(n)

        edge.decay_metrics.update(d)

        if n >= 40 and (t_stat < 1.0 or expectancy < 0.0):
            edge.state = "shadow"
            edge.active = False
        elif edge.state == "shadow" and n >= 60 and t_stat > 1.3 and expectancy > 0.0 and pf > 1.1:
            edge.state = "active"
            edge.active = True

    def apply_decay_guardrails(self, min_expectancy: float = 0.0, min_pf: float = 1.2, min_t: float = 1.5) -> None:
        for edge in self.entries.values():
            if float(edge.decay.get("samples", 0.0)) < 20:
                continue
            if (
                float(edge.decay.get("rolling_expectancy", 0.0)) < min_expectancy
                or float(edge.decay.get("rolling_pf", edge.stats.get("profit_factor", 0.0))) < min_pf
                or float(edge.decay.get("rolling_t_stat", edge.stats.get("t_stat", 0.0))) < min_t
            ):
                edge.active = False
                edge.state = "shadow"

    def lifecycle_summary(self) -> dict[str, int]:
        return {
            "active_edges": sum(1 for e in self.entries.values() if e.state == "active"),
            "shadow_edges": sum(1 for e in self.entries.values() if e.state == "shadow"),
            "retired_edges": sum(1 for e in self.entries.values() if e.state == "retired"),
        }

    def normalize_and_filter(self) -> int:
        filtered: dict[str, EdgeEntry] = {}
        removed = 0
        for edge_id, edge in self.entries.items():
            if self._edge_anomalous(edge):
                removed += 1
                continue
            filtered[edge_id] = edge
        self.entries = filtered
        return removed

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_version": self.active_version,
            "generated_at": self._now_iso(),
            "lifecycle": self.lifecycle_summary(),
            "edges": [e.__dict__ for e in self.entries.values()],
        }

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path, normalize: bool = False) -> "EdgeRegistry":
        p = Path(path)
        reg = cls()
        if not p.exists():
            return reg
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError, TypeError):
            return reg
        reg.active_version = payload.get("active_version")
        allowed_fields = {f.name for f in dataclasses.fields(EdgeEntry)}
        for row in payload.get("edges", []):
            # Backward compatible ingestion of pre-standardized edge schema.
            row = dict(row)
            row.setdefault("event_definition", str(row.get("event", "")))
            row.setdefault("confidence_score", float(row.get("stats", {}).get("t_stat", 0.0)))
            row.setdefault("expected_return", float(row.get("stats", {}).get("expectancy", 0.0)))
            horizon_val = row.get("horizon")
            if horizon_val is None or horizon_val == "":
                holding_period = 4
            else:
                try:
                    holding_period = int(horizon_val)
                except (TypeError, ValueError):
                    holding_period = 4
            row.setdefault("holding_period", holding_period)
            row.setdefault("regime", str(row.get("conditions", {}).get("regime", "unknown")))
            row.setdefault("asset_coverage", list(row.get("assets", [])))
            row.setdefault("sample_size", float(row.get("stats", {}).get("samples", 0.0)))
            row.setdefault("in_sample_metrics", dict(row.get("stats", {})))
            row.setdefault("out_of_sample_metrics", dict(row.get("oos_stats", {})))
            row.setdefault("decay_metrics", dict(row.get("decay", {})))
            row.setdefault("state", "active" if row.get("active", True) else "shadow")
            row.setdefault("pnl_window", [])
            filtered_row = {k: v for k, v in row.items() if k in allowed_fields}
            e = EdgeEntry(**filtered_row)
            reg.entries[e.edge_id] = e
        if normalize:
            reg.normalize_and_filter()
        return reg
