from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.src.research.edge_discovery import DiscoveryConfig


@dataclass
class EventResearchConfig:
    train_fraction: float = 0.70
    min_event_samples: int = 200
    min_oos_samples: int = 120
    min_oos_t_stat: float = 2.0
    min_oos_sharpe: float = 1.5
    min_oos_profit_factor: float = 1.2
    horizons_ms: tuple[int, ...] = (100, 500, 1000, 5000, 30000)
    eval_horizon_ms: int = 1000
    fee_bps: float = 0.9
    latency_penalty_bps: float = 0.8
    slippage_coef_bps: float = 2.2
    min_capture_hours: float = 12.0
    min_overlap_hours: float = 12.0
    min_symbol_capture_hours: float = 12.0
    max_gap_ms: int = 3000
    min_total_micro_events: int = 150000
    min_trades_per_hour: float = 3000.0
    min_books_per_hour: float = 12000.0
    max_sequence_break_rate: float = 0.005
    min_trade_burst_events: int = 100
    min_spread_widening_events: int = 60
    min_imbalance_shock_events: int = 100
    min_depth_change_events: int = 100
    event_cluster_window_ms: int = 500
    min_event_cluster_ratio: float = 0.20


class EventTimeMicrostructureEngine:
    def __init__(self, config: EventResearchConfig | None = None):
        self.config = config or EventResearchConfig()
        self._strict = DiscoveryConfig()

    @staticmethod
    def _safe_std(x: pd.Series) -> float:
        if len(x) < 2:
            return 0.0
        v = float(x.std())
        return v if np.isfinite(v) else 0.0

    def _stats(self, x: pd.Series, min_samples: int) -> dict[str, float]:
        s = pd.to_numeric(x, errors="coerce").dropna()
        n = int(s.shape[0])
        if n < min_samples:
            return {
                "samples": float(n),
                "expectancy": 0.0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "t_stat": 0.0,
                "sharpe": 0.0,
            }
        wins = s[s > 0.0]
        losses = s[s < 0.0]
        expectancy = float(s.mean())
        std = self._safe_std(s)
        pf = float(wins.sum() / abs(losses.sum())) if float(losses.sum()) != 0.0 else 10.0
        t_stat = float((expectancy / (std / np.sqrt(n))) if std > 1e-12 else 0.0)
        sharpe = float((expectancy / std) * np.sqrt(max(1.0, float(n)))) if std > 1e-12 else 0.0
        return {
            "samples": float(n),
            "expectancy": expectancy,
            "win_rate": float((s > 0.0).mean()),
            "profit_factor": pf,
            "t_stat": t_stat,
            "sharpe": sharpe,
        }

    @staticmethod
    def _parse_partition_value(path: Path, key: str) -> str:
        marker = f"{key}="
        for part in path.parts:
            if part.startswith(marker):
                return str(part[len(marker):])
        return ""

    @staticmethod
    def _normalize_levels(value: Any) -> list[tuple[float, float]]:
        if value is None:
            return []
        if isinstance(value, np.ndarray):
            value = value.tolist()
        if isinstance(value, pd.Series):
            value = value.tolist()
        if not isinstance(value, list):
            return []
        out: list[tuple[float, float]] = []
        for row in value:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            try:
                out.append((float(row[0]), float(row[1])))
            except Exception:
                continue
        return out

    def _read_dataset(self, root: Path, dataset: str) -> pd.DataFrame:
        base = root / dataset
        if not base.exists():
            return pd.DataFrame()
        files = sorted(base.rglob("*.parquet"))
        frames: list[pd.DataFrame] = []
        for file in files:
            try:
                df = pd.read_parquet(file)
            except Exception:
                continue
            if df.empty:
                continue
            venue = self._parse_partition_value(file, "venue")
            symbol = self._parse_partition_value(file, "symbol")
            if "venue" not in df.columns and venue:
                df["venue"] = venue
            if "symbol" not in df.columns and symbol:
                df["symbol"] = symbol
            frames.append(df)
        if not frames:
            return pd.DataFrame()
        out = pd.concat(frames, axis=0, ignore_index=True)
        if "exchange_ts_ms" in out.columns:
            ts_col = pd.to_numeric(out["exchange_ts_ms"], errors="coerce")
        else:
            ts_col = pd.Series(0, index=out.index, dtype="int64")
        out["exchange_ts_ms"] = ts_col.fillna(0).astype("int64")
        out["ts"] = pd.to_datetime(out["exchange_ts_ms"], unit="ms", utc=True, errors="coerce")
        out = out.dropna(subset=["ts"])
        return out.sort_values("exchange_ts_ms")

    @staticmethod
    def _apply_book_delta(levels: dict[float, float], updates: list[tuple[float, float]]) -> tuple[float, float, float]:
        add_flow = 0.0
        cancel_flow = 0.0
        queue_delta = 0.0
        for price, qty in updates:
            px = float(price)
            q_new = max(0.0, float(qty))
            q_old = float(levels.get(px, 0.0))
            d = q_new - q_old
            if d > 0:
                add_flow += d
            elif d < 0:
                cancel_flow += abs(d)
            queue_delta += d
            if q_new <= 0.0:
                levels.pop(px, None)
            else:
                levels[px] = q_new
        return add_flow, cancel_flow, queue_delta

    @staticmethod
    def _book_top(levels: dict[float, float], side: str) -> tuple[float, float]:
        if not levels:
            return 0.0, 0.0
        px = max(levels.keys()) if side == "bid" else min(levels.keys())
        return float(px), float(levels.get(px, 0.0))

    def _build_event_clock_stream(self, trades: pd.DataFrame, books: pd.DataFrame) -> dict[tuple[str, str], pd.DataFrame]:
        out: dict[tuple[str, str], pd.DataFrame] = {}
        keys_t = set((str(v), str(s)) for v, s in zip(trades.get("venue", []), trades.get("symbol", [])))
        keys_b = set((str(v), str(s)) for v, s in zip(books.get("venue", []), books.get("symbol", [])))
        keys = sorted(keys_t | keys_b)

        for venue, symbol in keys:
            t = trades[(trades["venue"] == venue) & (trades["symbol"] == symbol)].copy()
            b = books[(books["venue"] == venue) & (books["symbol"] == symbol)].copy()
            if t.empty and b.empty:
                continue

            events: list[dict[str, Any]] = []
            if not t.empty:
                t = t.sort_values(["exchange_ts_ms", "sequence_id" if "sequence_id" in t.columns else "exchange_ts_ms"])
                t["kind"] = "trade"
                for _, row in t.iterrows():
                    events.append(
                        {
                            "kind": "trade",
                            "exchange_ts_ms": int(row.get("exchange_ts_ms", 0) or 0),
                            "sequence": int(row.get("sequence_id", 0) or 0),
                            "price": float(row.get("price", 0.0) or 0.0),
                            "quantity": float(row.get("quantity", 0.0) or 0.0),
                            "side": str(row.get("side", "buy") or "buy").lower(),
                        }
                    )
            if not b.empty:
                b = b.sort_values(["exchange_ts_ms", "first_update_id" if "first_update_id" in b.columns else "exchange_ts_ms", "update_id" if "update_id" in b.columns else "exchange_ts_ms"])
                for _, row in b.iterrows():
                    events.append(
                        {
                            "kind": "book",
                            "exchange_ts_ms": int(row.get("exchange_ts_ms", 0) or 0),
                            "sequence": int(row.get("first_update_id", row.get("update_id", 0)) or 0),
                            "bids": self._normalize_levels(row.get("bid_levels", [])),
                            "asks": self._normalize_levels(row.get("ask_levels", [])),
                            "is_snapshot": bool(row.get("is_snapshot", False)),
                            "book_mode": str(row.get("book_mode", "snapshot") or "snapshot"),
                            "first_update_id": int(row.get("first_update_id", row.get("update_id", 0)) or 0),
                            "update_id": int(row.get("update_id", 0) or 0),
                            "prev_update_id": int(row.get("prev_update_id", 0) or 0),
                        }
                    )

            if not events:
                continue
            events.sort(key=lambda x: (int(x["exchange_ts_ms"]), 0 if x["kind"] == "book" else 1, int(x.get("sequence", 0))))

            bids: dict[float, float] = {}
            asks: dict[float, float] = {}
            state_rows: list[dict[str, Any]] = []
            last_mid = 0.0
            last_imb = 0.0
            recent_depth: list[float] = []
            last_sweep_ts = -1
            last_book_update_id = 0

            for e in events:
                ts = int(e["exchange_ts_ms"])
                add_flow = 0.0
                cancel_flow = 0.0
                queue_delta = 0.0
                signed_trade = 0.0
                trade_qty = 0.0
                trade_px = np.nan

                if e["kind"] == "book":
                    if bool(e.get("is_snapshot", False)):
                        bids = {float(p): float(q) for p, q in e.get("bids", []) if float(q) > 0}
                        asks = {float(p): float(q) for p, q in e.get("asks", []) if float(q) > 0}
                    else:
                        a1, c1, q1 = self._apply_book_delta(bids, [(float(p), float(q)) for p, q in e.get("bids", [])])
                        a2, c2, q2 = self._apply_book_delta(asks, [(float(p), float(q)) for p, q in e.get("asks", [])])
                        add_flow = a1 + a2
                        cancel_flow = c1 + c2
                        queue_delta = q1 + q2
                    last_book_update_id = int(e.get("update_id", last_book_update_id) or last_book_update_id)

                else:
                    trade_qty = float(e.get("quantity", 0.0) or 0.0)
                    side = str(e.get("side", "buy"))
                    signed_trade = trade_qty if side == "buy" else -trade_qty
                    trade_px = float(e.get("price", np.nan))

                best_bid, _ = self._book_top(bids, "bid")
                best_ask, _ = self._book_top(asks, "ask")
                mid = (best_bid + best_ask) / 2.0 if best_bid > 0 and best_ask > 0 else last_mid
                spread_bps = ((best_ask - best_bid) / mid * 10000.0) if mid > 0 and best_ask > best_bid else 0.0

                bid_depth = float(sum(v for _, v in sorted(bids.items(), reverse=True)[:20]))
                ask_depth = float(sum(v for _, v in sorted(asks.items(), key=lambda x: x[0])[:20]))
                depth_total = bid_depth + ask_depth
                imbalance = ((bid_depth - ask_depth) / depth_total) if depth_total > 0 else 0.0
                imbalance_delta = imbalance - last_imb
                depth_drop = 0.0
                if recent_depth:
                    prev_depth = max(1e-9, recent_depth[-1])
                    depth_drop = max(0.0, (prev_depth - depth_total) / prev_depth)

                sweep_flag = 1.0 if (depth_drop > 0.12 and abs(imbalance_delta) > 0.12) else 0.0
                if sweep_flag > 0:
                    last_sweep_ts = ts
                elapsed_since_sweep_ms = max(0, ts - last_sweep_ts) if last_sweep_ts > 0 else 999999
                refill_speed = (add_flow / max(cancel_flow, 1e-9)) if cancel_flow > 0 else (add_flow if add_flow > 0 else 0.0)
                refill_failure = 1.0 if (elapsed_since_sweep_ms <= 500 and refill_speed < 0.8 and depth_drop > 0.05) else 0.0

                if mid > 0 and last_mid > 0:
                    ret_ms = (mid / last_mid) - 1.0
                else:
                    ret_ms = 0.0

                state_rows.append(
                    {
                        "exchange_ts_ms": ts,
                        "ts": pd.to_datetime(ts, unit="ms", utc=True),
                        "venue": venue,
                        "symbol": symbol,
                        "mid_price": float(mid),
                        "spread_bps": float(spread_bps),
                        "depth_total": float(depth_total),
                        "imbalance": float(imbalance),
                        "imbalance_delta": float(imbalance_delta),
                        "queue_position_change": float(queue_delta),
                        "add_flow": float(add_flow),
                        "cancel_flow": float(cancel_flow),
                        "refill_speed": float(refill_speed),
                        "sweep_flag": float(sweep_flag),
                        "queue_collapse_flag": float(1.0 if (cancel_flow > add_flow * 1.8 and depth_drop > 0.08) else 0.0),
                        "refill_failure_flag": float(refill_failure),
                        "trade_qty": float(trade_qty),
                        "signed_trade_qty": float(signed_trade),
                        "trade_price": float(trade_px) if np.isfinite(float(trade_px)) else np.nan,
                        "ret_ms": float(ret_ms),
                        "book_update_id": int(last_book_update_id),
                    }
                )

                if depth_total > 0:
                    recent_depth.append(float(depth_total))
                    if len(recent_depth) > 200:
                        recent_depth = recent_depth[-200:]
                last_mid = float(mid)
                last_imb = float(imbalance)

            frame = pd.DataFrame(state_rows)
            if frame.empty:
                continue
            out[(venue, symbol)] = frame

        return out

    def _bin_ms(self, frame: pd.DataFrame, bin_ms: int = 10) -> pd.DataFrame:
        if frame.empty:
            return frame
        df = frame.copy()
        df["bucket_ms"] = (df["exchange_ts_ms"] // bin_ms) * bin_ms
        agg = df.groupby("bucket_ms", dropna=False).agg(
            venue=("venue", "last"),
            symbol=("symbol", "last"),
            mid_price=("mid_price", "last"),
            spread_bps=("spread_bps", "last"),
            depth_total=("depth_total", "last"),
            imbalance=("imbalance", "last"),
            imbalance_delta=("imbalance_delta", "mean"),
            queue_position_change=("queue_position_change", "sum"),
            add_flow=("add_flow", "sum"),
            cancel_flow=("cancel_flow", "sum"),
            refill_speed=("refill_speed", "mean"),
            sweep_flag=("sweep_flag", "max"),
            queue_collapse_flag=("queue_collapse_flag", "max"),
            refill_failure_flag=("refill_failure_flag", "max"),
            trade_qty=("trade_qty", "sum"),
            signed_trade_qty=("signed_trade_qty", "sum"),
            ret_ms=("ret_ms", "sum"),
        ).reset_index()
        agg["exchange_ts_ms"] = agg["bucket_ms"].astype("int64")
        agg["ts"] = pd.to_datetime(agg["exchange_ts_ms"], unit="ms", utc=True)
        agg = agg.sort_values("exchange_ts_ms")
        return agg

    def _event_detection(self, frame_10ms: pd.DataFrame) -> pd.DataFrame:
        if frame_10ms.empty:
            return pd.DataFrame()
        f = frame_10ms.copy()
        w = int(max(50, min(300, len(f) // 5)))

        vol_z = ((f["trade_qty"] - f["trade_qty"].rolling(w).mean()) / f["trade_qty"].rolling(w).std().replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        abs_imb_delta = f["imbalance_delta"].abs()
        abs_imb = f["imbalance"].abs()
        spread_move = f["spread_bps"].diff().fillna(0.0)
        ofi = (f["signed_trade_qty"].fillna(0.0) + f["add_flow"].fillna(0.0) - f["cancel_flow"].fillna(0.0))
        ofi_abs = ofi.abs()
        cancel_dom = (f["cancel_flow"] - f["add_flow"]).fillna(0.0)

        q_imb90 = abs_imb_delta.rolling(w).quantile(0.90).fillna(abs_imb_delta.quantile(0.90))
        q_imb95 = abs_imb_delta.rolling(w).quantile(0.95).fillna(abs_imb_delta.quantile(0.95))
        q_absimb95 = abs_imb.rolling(w).quantile(0.95).fillna(abs_imb.quantile(0.95))
        q_ofi95 = ofi_abs.rolling(w).quantile(0.95).fillna(ofi_abs.quantile(0.95))
        q_cancel80 = cancel_dom.rolling(w).quantile(0.80).fillna(cancel_dom.quantile(0.80))

        # Robust event definitions at short captures: quantile-based, but still tied to true OFI/queue/spread dynamics.
        sweep = ((f["sweep_flag"] > 0.0) | (ofi_abs > q_ofi95)) & (cancel_dom > q_cancel80) & (abs_imb_delta > q_imb90)
        absorption = (vol_z > vol_z.quantile(0.95)) & (f["ret_ms"].abs() < f["ret_ms"].abs().rolling(w).quantile(0.50).fillna(0.0))
        imbalance_shock = (abs_imb_delta > q_imb95) | (abs_imb > q_absimb95)
        queue_collapse = (f["queue_collapse_flag"] > 0.0)
        refill_failure = (f["refill_failure_flag"] > 0.0)
        spread_wide_threshold = float(spread_move.quantile(0.95))
        spread_narrow_threshold = float(spread_move.quantile(0.05))

        rows: list[dict[str, Any]] = []
        for pos in range(len(f)):
            row = f.iloc[pos]
            is_sweep = bool(sweep.iloc[pos])
            is_absorption = bool(absorption.iloc[pos])
            is_queue_collapse = bool(queue_collapse.iloc[pos])
            is_refill_failure = bool(refill_failure.iloc[pos])
            cur_imb_delta_abs = float(abs_imb_delta.iloc[pos])
            cur_vol_z = float(vol_z.iloc[pos])
            cur_spread_move = float(spread_move.iloc[pos])
            sign = float(np.sign(row["signed_trade_qty"])) if float(row["signed_trade_qty"]) != 0.0 else float(np.sign(row["imbalance_delta"]))
            if sign == 0.0:
                continue

            candidates = [
                ("sweep_event", is_sweep, float(cur_imb_delta_abs + max(0.0, row["cancel_flow"] - row["add_flow"]))),
                ("absorption_event", is_absorption, float(cur_vol_z)),
                ("imbalance_shock", bool(imbalance_shock.iloc[pos]), float(cur_imb_delta_abs)),
                ("queue_collapse", is_queue_collapse, float(max(0.0, row["cancel_flow"] - row["add_flow"]))),
                ("refill_failure", is_refill_failure, float(max(0.0, 1.0 - row["refill_speed"]))),
                ("spread_widening", bool(cur_spread_move > spread_wide_threshold), float(max(0.0, cur_spread_move))),
                ("spread_narrowing", bool(cur_spread_move < spread_narrow_threshold), float(max(0.0, -cur_spread_move))),
            ]
            for et, trig, inten in candidates:
                if not trig:
                    continue
                rows.append(
                    {
                        "event_type": et,
                        "exchange_ts_ms": int(row["exchange_ts_ms"]),
                        "timestamp": row["ts"],
                        "venue": str(row["venue"]),
                        "symbol": str(row["symbol"]),
                        "event_sign": float(sign),
                        "event_intensity": float(max(0.0, inten)),
                        "pre_queue_position_change": float(row["queue_position_change"]),
                        "pre_imbalance_delta": float(row["imbalance_delta"]),
                        "pre_add_flow": float(row["add_flow"]),
                        "pre_cancel_flow": float(row["cancel_flow"]),
                        "pre_refill_speed": float(row["refill_speed"]),
                        "pre_spread_bps": float(row["spread_bps"]),
                        "pre_depth_total": float(row["depth_total"]),
                        "pre_mid_price": float(row["mid_price"]),
                    }
                )

        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).sort_values("exchange_ts_ms")

    def _attach_responses(self, events: pd.DataFrame, frame_10ms: pd.DataFrame) -> pd.DataFrame:
        if events.empty:
            return events
        price = frame_10ms[["exchange_ts_ms", "mid_price", "spread_bps", "trade_qty", "cancel_flow", "add_flow"]].copy()
        price = price.dropna(subset=["mid_price"]).sort_values("exchange_ts_ms")
        if price.empty:
            return pd.DataFrame()

        out = events.copy()
        for h in self.config.horizons_ms:
            out[f"ret_{h}ms"] = np.nan

        # Event-time response by exchange timestamp.
        px_series = price.set_index("exchange_ts_ms")["mid_price"]
        spread_series = price.set_index("exchange_ts_ms")["spread_bps"]
        qty_series = price.set_index("exchange_ts_ms")["trade_qty"]
        cancel_series = price.set_index("exchange_ts_ms")["cancel_flow"]
        add_series = price.set_index("exchange_ts_ms")["add_flow"]

        for idx, row in out.iterrows():
            ts = int(row["exchange_ts_ms"])
            if ts not in px_series.index:
                continue
            cur = float(px_series.loc[ts])
            if cur <= 0:
                continue
            for h in self.config.horizons_ms:
                target = ts + int(h)
                target_idx = px_series.index[px_series.index >= target]
                if target_idx.empty:
                    continue
                fwd_ts = int(target_idx[0])
                fwd = float(px_series.loc[fwd_ts])
                out.at[idx, f"ret_{h}ms"] = (fwd / cur) - 1.0

            spread = float(spread_series.loc[ts]) if ts in spread_series.index else 0.0
            qty = float(qty_series.loc[ts]) if ts in qty_series.index else 0.0
            depth_proxy = float(max(0.0, add_series.loc[ts] - cancel_series.loc[ts])) if ts in add_series.index and ts in cancel_series.index else 0.0
            slippage_bps = float(self.config.slippage_coef_bps * np.sqrt(max(0.0, qty) / max(1e-9, depth_proxy + qty)))
            cost_bps = float((spread * 0.5) + self.config.fee_bps + self.config.latency_penalty_bps + slippage_bps)
            out.at[idx, "cost_bps"] = cost_bps

        eval_h = int(self.config.eval_horizon_ms)
        eval_col = f"ret_{eval_h}ms"
        if eval_col not in out.columns:
            known = [int(h) for h in self.config.horizons_ms]
            fallback_h = min(known, key=lambda h: abs(h - eval_h)) if known else 100
            eval_col = f"ret_{fallback_h}ms"

        out["gross_ret"] = out["event_sign"] * out[eval_col]
        out["net_ret"] = out["gross_ret"] - (out["cost_bps"] / 10000.0)
        out["continuation_flag"] = ((out["event_sign"] * out[eval_col]) > 0.0)
        out["reversal_flag"] = ((out["event_sign"] * out[eval_col]) < 0.0)

        decay_speed = []
        for _, row in out.iterrows():
            impact = float(row.get("event_sign", 0.0) or 0.0) * float(row.get("ret_10ms", 0.0) or 0.0)
            if impact <= 0.0:
                decay_speed.append(float("nan"))
                continue
            threshold = 0.25 * impact
            found = float("nan")
            for h in self.config.horizons_ms:
                v = float(row.get("event_sign", 0.0) or 0.0) * float(row.get(f"ret_{h}ms", 0.0) or 0.0)
                if v <= threshold:
                    found = float(h)
                    break
            decay_speed.append(found)
        out["decay_speed_ms"] = decay_speed
        return out

    def _cross_venue_lag_events(self, streams_10ms: dict[tuple[str, str], pd.DataFrame]) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        symbols = sorted({sym for _, sym in streams_10ms.keys()})
        for symbol in symbols:
            venue_frames = {venue: df for (venue, sym), df in streams_10ms.items() if sym == symbol}
            if len(venue_frames) < 2:
                continue
            joined = None
            for venue, df in venue_frames.items():
                sub = df[["exchange_ts_ms", "mid_price"]].copy()
                sub.rename(columns={"mid_price": f"mid_{venue}"}, inplace=True)
                sub.set_index("exchange_ts_ms", inplace=True)
                if joined is None:
                    joined = sub
                else:
                    joined = joined.join(sub, how="outer")
            if joined is None or joined.empty:
                continue
            joined = joined.sort_index().ffill().dropna()
            if joined.empty:
                continue

            venues = sorted(venue_frames.keys())
            for i in range(len(venues)):
                for j in range(i + 1, len(venues)):
                    a = venues[i]
                    b = venues[j]
                    ra = joined[f"mid_{a}"].pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
                    rb = joined[f"mid_{b}"].pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
                    lag = ra.shift(1).rolling(300).corr(rb).replace([np.inf, -np.inf], np.nan).fillna(0.0)
                    same = ra.rolling(300).corr(rb).replace([np.inf, -np.inf], np.nan).fillna(0.0)
                    edge = (lag - same)
                    threshold = float(edge.quantile(0.995))
                    for ts in edge.index:
                        if float(edge.loc[ts]) <= threshold:
                            continue
                        sign = float(np.sign(ra.loc[ts]))
                        if sign == 0.0:
                            continue
                        rows.append(
                            {
                                "event_type": "cross_venue_lag",
                                "exchange_ts_ms": int(ts),
                                "timestamp": pd.to_datetime(int(ts), unit="ms", utc=True),
                                "venue": f"{a}->{b}",
                                "symbol": symbol,
                                "event_sign": sign,
                                "event_intensity": float(edge.loc[ts]),
                                "pre_queue_position_change": 0.0,
                                "pre_imbalance_delta": 0.0,
                                "pre_add_flow": 0.0,
                                "pre_cancel_flow": 0.0,
                                "pre_refill_speed": 0.0,
                                "pre_spread_bps": 0.0,
                                "pre_depth_total": 0.0,
                                "pre_mid_price": float(joined[f"mid_{a}"].loc[ts]),
                            }
                        )
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).sort_values("exchange_ts_ms")

    def _validate_capture_readiness(self, trades: pd.DataFrame, books: pd.DataFrame) -> tuple[bool, dict[str, Any], list[str], dict[str, str]]:
        reasons: list[str] = []
        metrics: dict[str, Any] = {
            "capture_hours": 0.0,
            "overlap_hours": 0.0,
            "min_symbol_capture_hours": 0.0,
            "event_density_per_hour": 0.0,
            "trade_frequency_per_hour": 0.0,
            "orderbook_update_rate_per_hour": 0.0,
            "max_observed_gap_ms": 0,
            "sequence_break_rate": 0.0,
            "total_micro_events": 0,
            "has_trade_orderbook_overlap": False,
            "continuous_timestamps": False,
            "sequence_continuity": False,
        }

        if trades.empty or books.empty:
            reasons.append("missing_trade_or_orderbook_stream")
            diagnosis = {
                "missing_information_dimension": "stream_overlap",
                "minimal_upgrade": "Capture synchronized trades and diff-depth streams for the same symbols and venues.",
            }
            return False, metrics, reasons, diagnosis

        trade_min = int(pd.to_numeric(trades["exchange_ts_ms"], errors="coerce").dropna().min())
        trade_max = int(pd.to_numeric(trades["exchange_ts_ms"], errors="coerce").dropna().max())
        book_min = int(pd.to_numeric(books["exchange_ts_ms"], errors="coerce").dropna().min())
        book_max = int(pd.to_numeric(books["exchange_ts_ms"], errors="coerce").dropna().max())

        global_start = min(trade_min, book_min)
        global_end = max(trade_max, book_max)
        overlap_start = max(trade_min, book_min)
        overlap_end = min(trade_max, book_max)

        capture_hours = max(0.0, (global_end - global_start) / 3_600_000.0)
        overlap_hours = max(0.0, (overlap_end - overlap_start) / 3_600_000.0)
        metrics["capture_hours"] = float(capture_hours)
        metrics["overlap_hours"] = float(overlap_hours)
        metrics["has_trade_orderbook_overlap"] = bool(overlap_end > overlap_start)

        if capture_hours < self.config.min_capture_hours:
            reasons.append("insufficient_capture_coverage")
        if overlap_hours < self.config.min_overlap_hours:
            reasons.append("insufficient_trade_orderbook_overlap")

        # Require each venue-symbol stream to satisfy minimum continuous capture window.
        symbol_capture_hours: list[float] = []
        t_pairs = trades.groupby(["venue", "symbol"], dropna=False)["exchange_ts_ms"].agg(["min", "max"])
        b_pairs = books.groupby(["venue", "symbol"], dropna=False)["exchange_ts_ms"].agg(["min", "max"])
        all_pairs = set(t_pairs.index.tolist()) | set(b_pairs.index.tolist())
        for pair in all_pairs:
            mins: list[int] = []
            maxs: list[int] = []
            if pair in t_pairs.index:
                mins.append(int(t_pairs.loc[pair, "min"]))
                maxs.append(int(t_pairs.loc[pair, "max"]))
            if pair in b_pairs.index:
                mins.append(int(b_pairs.loc[pair, "min"]))
                maxs.append(int(b_pairs.loc[pair, "max"]))
            if mins and maxs:
                symbol_capture_hours.append(max(0.0, (max(maxs) - min(mins)) / 3_600_000.0))
        min_symbol_hours = float(min(symbol_capture_hours)) if symbol_capture_hours else 0.0
        metrics["min_symbol_capture_hours"] = min_symbol_hours
        if min_symbol_hours < self.config.min_symbol_capture_hours:
            reasons.append("insufficient_symbol_capture_coverage")

        overlap_trades = trades[(trades["exchange_ts_ms"] >= overlap_start) & (trades["exchange_ts_ms"] <= overlap_end)].copy()
        overlap_books = books[(books["exchange_ts_ms"] >= overlap_start) & (books["exchange_ts_ms"] <= overlap_end)].copy()

        total_events = int(len(overlap_trades) + len(overlap_books))
        metrics["total_micro_events"] = total_events
        if overlap_hours > 0:
            metrics["event_density_per_hour"] = float(total_events / overlap_hours)
            metrics["trade_frequency_per_hour"] = float(len(overlap_trades) / overlap_hours)
            metrics["orderbook_update_rate_per_hour"] = float(len(overlap_books) / overlap_hours)

        if total_events < self.config.min_total_micro_events:
            reasons.append("insufficient_event_density")
        if float(metrics["trade_frequency_per_hour"]) < self.config.min_trades_per_hour:
            reasons.append("low_trade_frequency")
        if float(metrics["orderbook_update_rate_per_hour"]) < self.config.min_books_per_hour:
            reasons.append("low_orderbook_update_rate")

        combined_ts = pd.concat(
            [
                pd.to_numeric(overlap_trades["exchange_ts_ms"], errors="coerce"),
                pd.to_numeric(overlap_books["exchange_ts_ms"], errors="coerce"),
            ],
            ignore_index=True,
        ).dropna()
        combined_ts = combined_ts.astype("int64").sort_values()
        if len(combined_ts) > 1:
            max_gap_ms = int(combined_ts.diff().fillna(0).max())
        else:
            max_gap_ms = 0
        metrics["max_observed_gap_ms"] = max_gap_ms
        metrics["continuous_timestamps"] = bool(max_gap_ms <= self.config.max_gap_ms)
        if max_gap_ms > self.config.max_gap_ms:
            reasons.append("timestamp_gaps_detected")

        seq_breaks = 0
        seq_checks = 0
        if "update_id" in overlap_books.columns and "is_snapshot" in overlap_books.columns:
            for (venue, _), grp in overlap_books.sort_values(["venue", "symbol", "exchange_ts_ms"]).groupby(["venue", "symbol"], dropna=False):
                last_update_id = 0
                for _, row in grp.iterrows():
                    is_snapshot = bool(row.get("is_snapshot", False))
                    update_id = int(row.get("update_id", 0) or 0)
                    prev_update_id = int(row.get("prev_update_id", 0) or 0)
                    first_update_id = int(row.get("first_update_id", update_id) or update_id)
                    if is_snapshot:
                        last_update_id = update_id
                        continue
                    seq_checks += 1
                    if first_update_id > update_id:
                        seq_breaks += 1
                    elif str(venue).lower() == "binance":
                        if prev_update_id > 0 and last_update_id > 0 and prev_update_id != last_update_id:
                            seq_breaks += 1
                    else:
                        # Non-Binance venues often expose alternate sequencing metadata.
                        # Require monotonic orderbook update ids instead of strict parent links.
                        if last_update_id > 0 and update_id > 0 and update_id <= last_update_id:
                            seq_breaks += 1
                    last_update_id = update_id if update_id > 0 else last_update_id

        break_rate = float(seq_breaks / seq_checks) if seq_checks > 0 else 1.0
        metrics["sequence_break_rate"] = break_rate
        metrics["sequence_continuity"] = bool(seq_checks > 0 and break_rate <= self.config.max_sequence_break_rate)
        if not bool(metrics["sequence_continuity"]):
            reasons.append("sequence_discontinuity")

        diagnosis_map = {
            "insufficient_capture_coverage": ("coverage_window", "Capture at least 12h of uninterrupted microstructure data before discovery."),
            "insufficient_symbol_capture_coverage": ("coverage_window", "Capture at least 12h continuous trades and orderbook updates per venue/symbol pair."),
            "insufficient_trade_orderbook_overlap": ("stream_overlap", "Ensure trade and orderbook streams overlap for the same 12h window."),
            "insufficient_event_density": ("event_density", "Increase event density by extending capture duration and symbol coverage."),
            "low_trade_frequency": ("trade_frequency", "Increase number of active symbols/venues to raise trade observations per hour."),
            "low_orderbook_update_rate": ("orderbook_update_rate", "Capture higher-fidelity diff-depth updates with stable connectivity."),
            "timestamp_gaps_detected": ("timestamp_continuity", "Eliminate feed interruptions and reconnect gaps in realtime ingestion."),
            "sequence_discontinuity": ("sequence_continuity", "Repair diff-depth sequence continuity using snapshot recovery and strict update chaining."),
            "missing_trade_or_orderbook_stream": ("stream_overlap", "Capture synchronized trades and orderbook updates for every venue/symbol pair."),
        }

        if reasons:
            key = reasons[0]
            dim, upgrade = diagnosis_map.get(key, ("microstructure_quality", "Improve capture continuity and overlap before discovery."))
            return False, metrics, reasons, {"missing_information_dimension": dim, "minimal_upgrade": upgrade}
        return True, metrics, reasons, {"missing_information_dimension": "none", "minimal_upgrade": "none"}

    def _validate_event_dimension_coverage(self, events: pd.DataFrame) -> tuple[bool, dict[str, bool], dict[str, str]]:
        required = {
            "sweep_events": "sweep_event",
            "imbalance_events": "imbalance_shock",
            "spread_change_events": "spread_widening",
        }
        presence = {k: False for k in required.keys()}
        if events.empty or "event_type" not in events.columns:
            return False, presence, {
                "missing_information_dimension": "event_detection_power",
                "minimal_upgrade": "Increase capture quality to surface sweep, imbalance, and spread events.",
            }

        existing = set(pd.Series(events["event_type"]).astype(str).tolist())
        for key, val in required.items():
            presence[key] = bool(val in existing)

        counts = events["event_type"].value_counts(dropna=False)
        trade_bursts = int(counts.get("sweep_event", 0))
        spread_widening = int(counts.get("spread_widening", 0))
        imbalance_shocks = int(counts.get("imbalance_shock", 0))
        depth_changes = int(counts.get("queue_collapse", 0) + counts.get("refill_failure", 0))

        # Require clustered microstructure events instead of isolated noise.
        clustered = 0
        if not events.empty:
            sorted_events = events[["event_type", "exchange_ts_ms"]].copy().sort_values(["event_type", "exchange_ts_ms"])
            for _, grp in sorted_events.groupby("event_type", dropna=False):
                if len(grp) < 2:
                    continue
                diffs = pd.to_numeric(grp["exchange_ts_ms"], errors="coerce").diff().fillna(10**9)
                clustered += int((diffs <= int(self.config.event_cluster_window_ms)).sum())
        cluster_ratio = float(clustered / max(1, len(events)))

        density_failures: list[str] = []
        if trade_bursts < int(self.config.min_trade_burst_events):
            density_failures.append("trade_burst_events")
        if spread_widening < int(self.config.min_spread_widening_events):
            density_failures.append("spread_widening_events")
        if imbalance_shocks < int(self.config.min_imbalance_shock_events):
            density_failures.append("imbalance_shock_events")
        if depth_changes < int(self.config.min_depth_change_events):
            density_failures.append("depth_change_events")
        if cluster_ratio < float(self.config.min_event_cluster_ratio):
            density_failures.append("event_sequence_integrity")

        missing = [k for k, v in presence.items() if not v]
        if missing or density_failures:
            first = missing[0] if missing else density_failures[0]
            mapping = {
                "sweep_events": ("sweep_activity", "Add longer high-activity sessions to observe aggressive liquidity sweeps."),
                "imbalance_events": ("orderflow_imbalance", "Increase orderbook depth fidelity and capture duration for imbalance shocks."),
                "spread_change_events": ("spread_dynamics", "Include more volatile sessions where spread transitions are present."),
                "trade_burst_events": ("event_density", "Capture higher-activity windows until sweep/trade burst counts meet minimum density."),
                "spread_widening_events": ("spread_dynamics", "Capture more volatile sessions to surface spread transition events."),
                "imbalance_shock_events": ("orderflow_imbalance", "Improve diff-depth continuity to observe imbalance shock events."),
                "depth_change_events": ("depth_dynamics", "Capture longer sessions with reliable queue collapse/refill observations."),
                "event_sequence_integrity": ("sequence_integrity", "Increase continuity so events cluster in meaningful sequences, not isolated points."),
            }
            dim, upg = mapping[first]
            return False, presence, {"missing_information_dimension": dim, "minimal_upgrade": upg}

        return True, presence, {"missing_information_dimension": "none", "minimal_upgrade": "none"}

    def _evaluate_edges(self, events: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        if events.empty:
            return accepted, [{"reason": ["no_event_rows"]}]

        events = events.sort_values("exchange_ts_ms")
        split = int(len(events) * self.config.train_fraction)
        train = events.iloc[:split].copy()
        oos = events.iloc[split:].copy()
        if train.empty or oos.empty:
            return accepted, [{"reason": ["invalid_oos_split"]}]

        for event_type, grp_train in train.groupby("event_type", dropna=False):
            grp_oos = oos[oos["event_type"] == event_type]
            train_stats = self._stats(
                grp_train["net_ret"],
                min_samples=max(self.config.min_event_samples, self._strict.min_event_samples),
            )
            oos_stats = self._stats(
                grp_oos["net_ret"],
                min_samples=max(self.config.min_oos_samples, self._strict.min_oos_samples),
            )

            per_symbol = grp_oos.groupby("symbol", dropna=False)["net_ret"].mean()
            pos_share = float((per_symbol > 0.0).mean()) if len(per_symbol) else 0.0
            stability_std = float(per_symbol.std()) if len(per_symbol) > 1 else 0.0

            continuation_prob = float(grp_train["continuation_flag"].mean()) if len(grp_train) else 0.0
            reversal_prob = float(grp_train["reversal_flag"].mean()) if len(grp_train) else 0.0
            decay_speed = float(pd.to_numeric(grp_train["decay_speed_ms"], errors="coerce").median()) if len(grp_train) else float("nan")

            reasons: list[str] = []
            if int(train_stats["samples"]) < max(self.config.min_event_samples, self._strict.min_event_samples):
                reasons.append("insufficient_event_samples")
            if int(oos_stats["samples"]) < max(self.config.min_oos_samples, self._strict.min_oos_samples):
                reasons.append("insufficient_oos_samples")
            if float(train_stats["expectancy"]) <= 0.0:
                reasons.append("non_positive_train_expectancy")
            if float(oos_stats["expectancy"]) <= 0.0:
                reasons.append("non_positive_oos_expectancy")
            if float(oos_stats["t_stat"]) < max(self.config.min_oos_t_stat, self._strict.min_oos_t_stat):
                reasons.append("weak_oos_t_stat")
            if float(oos_stats.get("sharpe", 0.0)) < float(self.config.min_oos_sharpe):
                reasons.append("weak_oos_sharpe")
            if float(oos_stats["profit_factor"]) < max(self.config.min_oos_profit_factor, self._strict.min_oos_profit_factor):
                reasons.append("weak_oos_profit_factor")
            if len(per_symbol) < max(2, self._strict.min_assets_required):
                reasons.append("insufficient_cross_asset_coverage")
            if pos_share < 0.65:
                reasons.append("low_cross_asset_consistency")

            payload = {
                "edge_id": str(event_type),
                "event_type": str(event_type),
                "is_metrics": train_stats,
                "oos_metrics": oos_stats,
                "sample_counts": {
                    "train": int(len(grp_train)),
                    "oos": int(len(grp_oos)),
                    "total": int(len(grp_train) + len(grp_oos)),
                },
                "stability_metrics": {
                    "cross_asset_positive_share": pos_share,
                    "cross_asset_expectancy_std": stability_std,
                    "continuation_probability": continuation_prob,
                    "reversal_probability": reversal_prob,
                    "decay_speed_ms": decay_speed,
                },
            }
            if reasons:
                payload["reason"] = reasons
                rejected.append(payload)
            else:
                accepted.append(payload)

        accepted.sort(
            key=lambda x: (
                float(x["oos_metrics"]["expectancy"]),
                float(x["oos_metrics"]["t_stat"]),
                float(x["stability_metrics"]["cross_asset_positive_share"]),
            ),
            reverse=True,
        )
        return accepted, rejected

    @staticmethod
    def _diagnose_missing_dimension(events: pd.DataFrame, accepted: list[dict[str, Any]]) -> dict[str, Any]:
        if accepted:
            return {"missing_information_dimension": "none", "minimal_upgrade": "none"}
        if events.empty:
            return {
                "missing_information_dimension": "event_density",
                "minimal_upgrade": "Collect longer continuous sub-second sessions with synchronized trade and diff-depth streams.",
            }

        reasons: list[str] = []
        if "cost_bps" in events.columns:
            gross_col = events["gross_ret"] if "gross_ret" in events.columns else pd.Series(dtype=float)
            cost_col = events["cost_bps"] if "cost_bps" in events.columns else pd.Series(dtype=float)
            gross = pd.to_numeric(gross_col, errors="coerce").dropna()
            cost = pd.to_numeric(cost_col, errors="coerce").dropna() / 10000.0
            if not gross.empty and not cost.empty and float(gross.abs().median()) <= float(cost.median()):
                reasons.append("cost_headroom")
        if "event_type" in events.columns:
            counts = events["event_type"].value_counts()
            if not counts.empty and int(counts.max()) < 200:
                reasons.append("sample_density")
        if "venue" in events.columns:
            venue_count = events["venue"].nunique()
            if int(venue_count) < 2:
                reasons.append("cross_venue_synchronization")

        if not reasons:
            reasons.append("microstructure_resolution")

        mapping = {
            "cost_headroom": "Reduce effective trading cost via lower-latency colocated routing and tighter maker capture on the same events.",
            "sample_density": "Increase capture window to at least multiple weeks of uninterrupted sub-second data per symbol.",
            "cross_venue_synchronization": "Capture the same symbols simultaneously across at least two venues with clock-synced exchange timestamps.",
            "microstructure_resolution": "Add native full-depth incremental feeds with guaranteed sequence continuity and clock sync.",
        }
        primary = reasons[0]
        return {
            "missing_information_dimension": primary,
            "minimal_upgrade": mapping.get(primary, mapping["microstructure_resolution"]),
        }

    def discover(self, microstructure_root: str | Path) -> dict[str, Any]:
        root = Path(microstructure_root)
        trades_dir = root / "trades"
        orderbook_dir = root / "orderbook"

        if not trades_dir.exists() and not orderbook_dir.exists():
            diagnosis = {
                "missing_information_dimension": "data_absence",
                "minimal_upgrade": "Run realtime capture to accumulate sub-second trades and diff-depth updates before discovery.",
            }
            return {
                "top_edges": [],
                "metrics": {"status": "no_microstructure_data", **diagnosis},
                "event_samples": [],
                "rejected": [{"reason": ["no_microstructure_data"]}],
            }

        if not trades_dir.exists() or not orderbook_dir.exists():
            diagnosis = {
                "missing_information_dimension": "stream_overlap",
                "minimal_upgrade": "Capture both trades and diff-depth orderbook streams under the same microstructure root.",
            }
            reasons = ["missing_trade_stream" if not trades_dir.exists() else "missing_orderbook_stream"]
            return {
                "top_edges": [],
                "metrics": {"status": "capture_not_ready", **diagnosis},
                "event_samples": [],
                "rejected": [{"reason": reasons}],
            }

        trades = self._read_dataset(root, dataset="trades")
        books = self._read_dataset(root, dataset="orderbook")
        if trades.empty and books.empty:
            diagnosis = {
                "missing_information_dimension": "data_absence",
                "minimal_upgrade": "Run realtime capture to accumulate sub-second trades and diff-depth updates before discovery.",
            }
            return {
                "top_edges": [],
                "metrics": {"status": "no_microstructure_data", **diagnosis},
                "event_samples": [],
                "rejected": [{"reason": ["no_microstructure_data"]}],
            }

        capture_ok, capture_metrics, capture_reasons, capture_diagnosis = self._validate_capture_readiness(trades, books)
        if not capture_ok:
            return {
                "top_edges": [],
                "metrics": {"status": "capture_not_ready", **capture_metrics, **capture_diagnosis},
                "event_samples": [],
                "rejected": [{"reason": capture_reasons}],
            }

        streams = self._build_event_clock_stream(trades=trades, books=books)
        streams_10ms = {k: self._bin_ms(v, bin_ms=10) for k, v in streams.items()}

        event_frames: list[pd.DataFrame] = []
        for _, frame in streams_10ms.items():
            e = self._event_detection(frame)
            if not e.empty:
                e = self._attach_responses(e, frame)
                if not e.empty:
                    event_frames.append(e)

        cross = self._cross_venue_lag_events(streams_10ms)
        if not cross.empty:
            # attach responses using synthetic multi stream average from first available symbol frame
            for symbol in cross["symbol"].unique():
                symbol_frames = [f for (_, s), f in streams_10ms.items() if s == symbol]
                if not symbol_frames:
                    continue
                base = symbol_frames[0]
                csub = cross[cross["symbol"] == symbol]
                csub = self._attach_responses(csub, base)
                if not csub.empty:
                    event_frames.append(csub)

        if not event_frames:
            diagnosis = {
                "missing_information_dimension": "event_detection_power",
                "minimal_upgrade": "Increase diff-depth continuity and event observation length to raise true HFT event counts.",
            }
            return {
                "top_edges": [],
                "metrics": {"status": "no_events_detected", **diagnosis},
                "event_samples": [],
                "rejected": [{"reason": ["no_events_detected"]}],
            }

        events = pd.concat(event_frames, axis=0, ignore_index=True)
        events = events.sort_values("exchange_ts_ms").dropna(subset=["net_ret"])

        event_dims_ok, event_dims, event_dims_diagnosis = self._validate_event_dimension_coverage(events)
        if not event_dims_ok:
            counts = events["event_type"].value_counts(dropna=False)
            clustered = 0
            sorted_events = events[["event_type", "exchange_ts_ms"]].copy().sort_values(["event_type", "exchange_ts_ms"])
            for _, grp in sorted_events.groupby("event_type", dropna=False):
                if len(grp) < 2:
                    continue
                diffs = pd.to_numeric(grp["exchange_ts_ms"], errors="coerce").diff().fillna(10**9)
                clustered += int((diffs <= int(self.config.event_cluster_window_ms)).sum())
            return {
                "top_edges": [],
                "metrics": {
                    "status": "missing_event_dimensions",
                    **capture_metrics,
                    **event_dims,
                    "event_counts": {str(k): int(v) for k, v in counts.to_dict().items()},
                    "event_cluster_ratio": float(clustered / max(1, len(events))),
                    **event_dims_diagnosis,
                },
                "event_samples": [],
                "rejected": [{"reason": ["missing_required_event_dimensions"]}],
            }

        accepted, rejected = self._evaluate_edges(events)
        diagnosis = self._diagnose_missing_dimension(events, accepted)

        metrics = {
            "events_total": int(len(events)),
            "event_types": {str(k): int(v) for k, v in events["event_type"].value_counts(dropna=False).to_dict().items()},
            "accepted_edges": int(len(accepted)),
            "rejected_edges": int(len(rejected)),
            "resolution_ms": 10,
            "response_horizons_ms": list(self.config.horizons_ms),
            **capture_metrics,
            **event_dims,
            **diagnosis,
        }

        keep_cols = [
            "timestamp",
            "venue",
            "symbol",
            "event_type",
            "event_intensity",
            "event_sign",
            "pre_queue_position_change",
            "pre_imbalance_delta",
            "pre_add_flow",
            "pre_cancel_flow",
            "pre_refill_speed",
            "ret_10ms",
            "ret_50ms",
            "ret_100ms",
            "ret_500ms",
            "cost_bps",
            "net_ret",
        ]
        sample_cols = [c for c in keep_cols if c in events.columns]
        samples = events[sample_cols].head(300)

        return {
            "top_edges": accepted[:5],
            "metrics": metrics,
            "event_samples": samples.to_dict(orient="records"),
            "rejected": rejected,
        }
