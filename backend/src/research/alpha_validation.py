from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import pandas as pd

from backend.src.platform.alpha_engine import AlphaEngine
from backend.src.research.monte_carlo_engine import MonteCarloEngine
from backend.src.research.edge_discovery import DiscoveryConfig, EdgeDiscoveryEngine


@dataclass
class BacktestMetrics:
    profit_factor: float
    sharpe: float
    max_drawdown: float
    trades: int
    win_rate: float
    expectancy: float


class AlphaValidationEngine:
    """Strict walk-forward and stress-validation for the production alpha logic."""

    def __init__(
        self,
        fee_bps: float = 6.0,
        slippage_bps: float = 5.0,
        alpha_engine_factory: Callable[[], AlphaEngine] | None = None,
    ):
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self.alpha_engine_factory = alpha_engine_factory or (lambda: AlphaEngine())

    @staticmethod
    def _contiguous_ranges(positions: list[int]) -> list[tuple[int, int]]:
        if not positions:
            return []
        ranges: list[tuple[int, int]] = []
        start = positions[0]
        prev = positions[0]
        for pos in positions[1:]:
            if pos == prev + 1:
                prev = pos
                continue
            ranges.append((start, prev))
            start = pos
            prev = pos
        ranges.append((start, prev))
        return ranges

    @staticmethod
    def _aggregate_metrics(metrics_list: list[BacktestMetrics]) -> BacktestMetrics:
        if not metrics_list:
            return BacktestMetrics(
                profit_factor=0.0,
                sharpe=0.0,
                max_drawdown=0.0,
                trades=0,
                win_rate=0.0,
                expectancy=0.0,
            )

        total_trades = sum(m.trades for m in metrics_list)
        if total_trades <= 0:
            return BacktestMetrics(
                profit_factor=float(np.mean([m.profit_factor for m in metrics_list])),
                sharpe=float(np.mean([m.sharpe for m in metrics_list])),
                max_drawdown=float(np.mean([m.max_drawdown for m in metrics_list])),
                trades=0,
                win_rate=float(np.mean([m.win_rate for m in metrics_list])),
                expectancy=float(np.mean([m.expectancy for m in metrics_list])),
            )

        weighted = lambda values: float(
            np.average(values, weights=[max(1, m.trades) for m in metrics_list])
        )
        return BacktestMetrics(
            profit_factor=weighted([m.profit_factor for m in metrics_list]),
            sharpe=weighted([m.sharpe for m in metrics_list]),
            max_drawdown=weighted([m.max_drawdown for m in metrics_list]),
            trades=total_trades,
            win_rate=weighted([m.win_rate for m in metrics_list]),
            expectancy=weighted([m.expectancy for m in metrics_list]),
        )

    def _simulate_segment(
        self,
        df: pd.DataFrame,
        warmup_df: pd.DataFrame | None = None,
    ) -> tuple[BacktestMetrics, np.ndarray, dict[str, Any]]:
        df = df.copy().sort_index()
        frame = df.copy()
        frame["ts"] = frame.index.astype(str)
        frame = frame.reset_index(drop=True)
        cost = (self.fee_bps + self.slippage_bps) / 10000.0

        returns: list[float] = []
        trade_returns: list[float] = []
        edge_returns: dict[str, list[float]] = {}

        signal_engine = self.alpha_engine_factory()

        def _tick_from_row(row: pd.Series) -> dict[str, Any]:
            tick: dict[str, Any] = {
                "symbol": "BTCUSDT",
                "price": float(row["close"]),
                "volume": float(row.get("volume", 0.0)),
                "ts": str(row["ts"]),
            }
            for col in row.index:
                if col in {"open", "high", "low", "close", "volume", "ts"}:
                    continue
                value = row.get(col)
                if pd.isna(value):
                    continue
                try:
                    tick[col] = float(value)
                except Exception:
                    continue
            return tick

        if warmup_df is not None and not warmup_df.empty:
            warmup = warmup_df.copy().sort_index()
            warmup["ts"] = warmup.index.astype(str)
            warmup = warmup.reset_index(drop=True)
            for i in range(len(warmup)):
                row = warmup.iloc[i]
                signal_engine.on_tick(_tick_from_row(row))

        horizon = 4
        for i in range(len(frame)):
            row = frame.iloc[i]
            tick = _tick_from_row(row)
            signal = signal_engine.on_tick(tick)
            if signal is None:
                returns.append(0.0)
                continue

            if i + horizon >= len(frame):
                continue

            px0 = float(frame.iloc[i]["close"])
            px1 = float(frame.iloc[i + horizon]["close"])
            if abs(px0) < 1e-12:
                raw = 0.0
            else:
                raw = (px1 / px0 - 1.0)
            signed = raw if signal["side"] == "buy" else -raw
            net = signed - cost
            returns.append(net)
            trade_returns.append(net)
            edge_id = str(signal.get("selected_edge", "unattributed"))
            edge_returns.setdefault(edge_id, []).append(float(net))

        arr = np.array(returns, dtype=float)
        trades = np.array(trade_returns, dtype=float)

        wins = trades[trades > 0]
        losses = trades[trades < 0]
        pf = float(wins.sum() / abs(losses.sum())) if losses.size > 0 else 10.0
        sharpe = float((arr.mean() / arr.std()) * np.sqrt(24 * 365)) if arr.std() > 1e-12 else 0.0

        equity = np.cumprod(1.0 + arr)
        peak = np.maximum.accumulate(equity)
        dd = (equity - peak) / peak
        max_dd = float(dd.min()) if dd.size else 0.0

        metrics = BacktestMetrics(
            profit_factor=pf,
            sharpe=sharpe,
            max_drawdown=abs(max_dd),
            trades=int(trades.size),
            win_rate=float((trades > 0).mean()) if trades.size else 0.0,
            expectancy=float(trades.mean()) if trades.size else 0.0,
        )

        edge_report: dict[str, Any] = {}
        for edge_id, vals in edge_returns.items():
            arr_e = np.array(vals, dtype=float)
            if arr_e.size == 0:
                continue
            wins_e = arr_e[arr_e > 0]
            losses_e = arr_e[arr_e < 0]
            pf_e = float(wins_e.sum() / abs(losses_e.sum())) if losses_e.size > 0 else 10.0
            std_e = float(arr_e.std())
            exp_e = float(arr_e.mean())
            t_e = float((exp_e / (std_e / np.sqrt(arr_e.size))) if std_e > 1e-9 else 0.0)
            edge_report[edge_id] = {
                "trades": int(arr_e.size),
                "expectancy": exp_e,
                "win_rate": float((arr_e > 0).mean()),
                "profit_factor": pf_e,
                "t_stat": t_e,
                "contribution_pnl": float(arr_e.sum()),
            }

        return metrics, trades, edge_report

    def run_backtest(self, df: pd.DataFrame) -> tuple[BacktestMetrics, np.ndarray]:
        metrics, trades, _ = self._simulate_segment(df, warmup_df=None)
        return metrics, trades

    def run_backtest_with_edge_report(self, df: pd.DataFrame) -> tuple[BacktestMetrics, np.ndarray, dict[str, Any]]:
        return self._simulate_segment(df, warmup_df=None)

    def discover_top_edges(self, df: pd.DataFrame, top_n: int = 5) -> list[dict[str, Any]]:
        if df.empty:
            return []
        frame = df.copy().sort_index()
        if len(frame) < 220:
            return []
        discovery = EdgeDiscoveryEngine(
            DiscoveryConfig(
                min_assets_required=1,
                max_top_edges=max(1, int(top_n)),
            )
        )
        result = discovery.discover({"BTC-USD": frame})
        return list(result.get("top_edges", []))[: max(1, int(top_n))]

    def compare_with_without_flow(self, df: pd.DataFrame) -> dict[str, Any]:
        flow_cols = [
            "open_interest",
            "open_interest_value",
            "funding_rate",
            "long_short_ratio",
            "long_account",
            "short_account",
            "liquidation_long_usd",
            "liquidation_short_usd",
        ]

        with_flow_metrics, with_flow_trades = self.run_backtest(df)

        no_flow = df.copy()
        for col in flow_cols:
            if col in no_flow.columns:
                no_flow[col] = 0.0

        without_flow_metrics, without_flow_trades = self.run_backtest(no_flow)

        def _safe_delta(a: float, b: float) -> float:
            return float(a - b)

        return {
            "with_flow": {
                "metrics": with_flow_metrics.__dict__,
                "trades": int(with_flow_trades.size),
            },
            "without_flow": {
                "metrics": without_flow_metrics.__dict__,
                "trades": int(without_flow_trades.size),
            },
            "delta": {
                "profit_factor": _safe_delta(with_flow_metrics.profit_factor, without_flow_metrics.profit_factor),
                "sharpe": _safe_delta(with_flow_metrics.sharpe, without_flow_metrics.sharpe),
                "max_drawdown": _safe_delta(with_flow_metrics.max_drawdown, without_flow_metrics.max_drawdown),
                "trades": int(with_flow_metrics.trades - without_flow_metrics.trades),
                "win_rate": _safe_delta(with_flow_metrics.win_rate, without_flow_metrics.win_rate),
                "expectancy": _safe_delta(with_flow_metrics.expectancy, without_flow_metrics.expectancy),
            },
        }

    def regime_segmented_backtest(
        self,
        df: pd.DataFrame,
        min_history: int = 140,
        min_segment_bars: int = 80,
        warmup_bars: int = 240,
    ) -> dict[str, Any]:
        """Evaluate performance stability by market regime segments."""
        frame = df.copy().sort_index()
        if len(frame) < max(min_history + 1, min_segment_bars + 1):
            return {"error": "insufficient_data"}

        work = frame.copy()
        close = work["close"].astype(float)
        returns = close.pct_change().fillna(0.0)
        vol20 = returns.rolling(20).std().fillna(0.0)
        avg_vol = float(vol20.mean()) if len(vol20) > 0 else 0.0

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        ema_spread = (ema12 - ema26).abs() / close.replace(0.0, np.nan)
        ema_spread = ema_spread.fillna(0.0)

        high_vol = vol20 > (avg_vol * 1.5)
        trend = (~high_vol) & (ema_spread >= 0.004)
        market_state = np.where(high_vol, "VOLATILE", np.where(trend, "TREND", "RANGE"))
        volatility = np.where(high_vol, "high_volatility", np.where(vol20 > avg_vol, "elevated_volatility", "low_volatility"))

        regime_points = [
            {
                "idx": i,
                "market_state": str(market_state[i]),
                "volatility": str(volatility[i]),
            }
            for i in range(min_history, len(frame))
        ]

        segment_positions: dict[str, list[int]] = {
            "trend": [
                p["idx"] for p in regime_points if p["market_state"] == "TREND"
            ],
            "range": [
                p["idx"] for p in regime_points if p["market_state"] == "RANGE"
            ],
            "high_volatility": [
                p["idx"]
                for p in regime_points
                if p["market_state"] == "VOLATILE"
                or p["volatility"] == "high_volatility"
            ],
        }

        out: dict[str, Any] = {}
        for label, positions in segment_positions.items():
            chunks = self._contiguous_ranges(positions)
            metrics_per_chunk: list[BacktestMetrics] = []
            all_trades: list[np.ndarray] = []
            covered_bars = 0

            for start, end in chunks:
                if (end - start + 1) < min_segment_bars:
                    continue
                test_df = frame.iloc[start : end + 1]
                covered_bars += int(end - start + 1)
                warmup_start = max(0, start - warmup_bars)
                warmup_df = frame.iloc[warmup_start:start]
                metrics, trades, _ = self._simulate_segment(test_df, warmup_df=warmup_df)
                metrics_per_chunk.append(metrics)
                all_trades.append(trades)

            if not metrics_per_chunk:
                out[label] = {
                    "sufficient": False,
                    "segments": 0,
                    "bars_covered": 0,
                    "coverage_ratio": 0.0,
                    "metrics": BacktestMetrics(0.0, 0.0, 0.0, 0, 0.0, 0.0).__dict__,
                }
                continue

            combined = self._aggregate_metrics(metrics_per_chunk)
            coverage_ratio = float(covered_bars / max(1, len(frame)))
            out[label] = {
                "sufficient": True,
                "segments": len(metrics_per_chunk),
                "bars_covered": covered_bars,
                "coverage_ratio": coverage_ratio,
                "metrics": combined.__dict__,
            }

        return out

    def walk_forward(self, df: pd.DataFrame, windows: int = 6) -> dict[str, Any]:
        n = len(df)
        chunk = n // windows
        results = []
        for i in range(1, windows):
            train_end = i * chunk
            test_end = min((i + 1) * chunk, n)
            if test_end - train_end < 80:
                continue
            train_df = df.iloc[:train_end]
            test_df = df.iloc[train_end:test_end]
            m, _, _ = self._simulate_segment(test_df, warmup_df=train_df)
            results.append(m)

        if not results:
            return {"error": "insufficient_data"}

        return {
            "windows": len(results),
            "profit_factor_mean": float(np.mean([r.profit_factor for r in results])),
            "sharpe_mean": float(np.mean([r.sharpe for r in results])),
            "max_drawdown_mean": float(np.mean([r.max_drawdown for r in results])),
            "trades_mean": float(np.mean([r.trades for r in results])),
            "windows_detail": [r.__dict__ for r in results],
        }

    def monte_carlo(self, trade_returns: np.ndarray, n_paths: int = 5000) -> dict[str, Any]:
        mc = MonteCarloEngine(initial_capital=1.0)
        return mc.simulate(trade_returns, n_paths=n_paths)

    @staticmethod
    def passes_targets(metrics: BacktestMetrics) -> bool:
        return (
            metrics.profit_factor > 1.3
            and metrics.sharpe > 1.5
            and metrics.max_drawdown < 0.10
            and metrics.trades > 100
        )

    @staticmethod
    def promotion_criteria(
        backtest: BacktestMetrics,
        walk_forward: dict[str, Any],
        regime_report: dict[str, Any],
        live_shadow: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        live_shadow = live_shadow or {}
        wf_pf = float(walk_forward.get("profit_factor_mean", 0.0) or 0.0)
        wf_sharpe = float(walk_forward.get("sharpe_mean", 0.0) or 0.0)

        stable_regimes = True
        for key, row in regime_report.items():
            if not isinstance(row, dict):
                continue
            if not row.get("sufficient", False):
                stable_regimes = False
                continue
            rm = row.get("metrics", {}) or {}
            if float(rm.get("profit_factor", 0.0) or 0.0) <= 1.0:
                stable_regimes = False

        live_pf = float(live_shadow.get("rolling_window_pf", live_shadow.get("rolling_7d_pf", 0.0)) or 0.0)
        live_trades = int(live_shadow.get("trade_count", 0) or 0)
        live_shadow_present = bool(live_shadow)

        checks = {
            "profit_factor": backtest.profit_factor > 1.3,
            "sharpe": backtest.sharpe > 1.5,
            "max_drawdown": backtest.max_drawdown < 0.10,
            "trade_count": backtest.trades > 100,
            "walk_forward_consistency": wf_pf > 1.1 and wf_sharpe > 1.0,
            "regime_stability": stable_regimes,
            "live_shadow_gate": (live_pf > 1.1 and live_trades >= 100) if live_shadow_present else True,
        }
        approved = all(bool(v) for v in checks.values())
        return {
            "approved": approved,
            "checks": checks,
            "details": {
                "backtest": backtest.__dict__,
                "walk_forward": walk_forward,
                "live_shadow": live_shadow,
            },
            "policy": "do_not_trade_if_any_check_fails",
        }
