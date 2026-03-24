from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import math

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.src.platform.alpha_engine import AlphaEngine
from backend.src.platform.market_context import MarketContextFetcher


def _bars_per_year(interval: str, trading_days_per_year: float = 365.0) -> float:
    v = str(interval).strip().lower()
    try:
        if v.endswith("m"):
            minutes = float(v[:-1])
            if minutes <= 0:
                return 24.0 * trading_days_per_year
            return (1440.0 / minutes) * trading_days_per_year
        if v.endswith("h"):
            hours = float(v[:-1])
            if hours <= 0:
                return 24.0 * trading_days_per_year
            return (24.0 / hours) * trading_days_per_year
        if v.endswith("d"):
            days = float(v[:-1])
            if days <= 0:
                return trading_days_per_year
            return trading_days_per_year / days
    except (TypeError, ValueError):
        return 24.0 * trading_days_per_year
    return 24.0 * trading_days_per_year


def _fetch(symbol: str, period: str, interval: str) -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval=interval, auto_adjust=False, progress=False)
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]).lower() for c in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]
    required_cols = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        return pd.DataFrame()
    base = df.reindex(columns=required_cols).dropna().sort_index()
    base.index = pd.to_datetime(base.index, utc=True)
    return MarketContextFetcher().enrich_ohlcv(base, symbol=symbol, interval=interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic shadow trading over historical bars")
    parser.add_argument("--symbol", default="BTC-USD")
    parser.add_argument("--period", default="60d")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--registry", default="data/edge_registry.json")
    parser.add_argument("--output-dir", default="data")
    args = parser.parse_args()

    frame = _fetch(args.symbol, args.period, args.interval)
    if frame.empty:
        raise RuntimeError("shadow_trading_no_data")

    engine = AlphaEngine(edge_registry_path=args.registry)
    returns: list[float] = []
    trade_count = 0

    rows = frame.copy()
    rows["ts"] = pd.DatetimeIndex(frame.index)
    rows = rows.reset_index(drop=True)
    for i in range(len(rows)):
        row = rows.iloc[i]
        tick = {
            "symbol": args.symbol.replace("-", "").replace("/", ""),
            "price": float(row["close"]),
            "volume": float(row.get("volume", 0.0) or 0.0),
            "ts": pd.Timestamp(row["ts"]).isoformat(),
        }
        for col in rows.columns:
            if col in {"ts", "open", "high", "low", "close", "volume"}:
                continue
            value = row.get(col)
            if pd.isna(value):
                continue
            try:
                tick[col] = float(value)
            except Exception:
                continue

        signal = engine.on_tick(tick)
        if signal is None:
            continue

        horizon = 4
        if i + horizon >= len(rows):
            continue

        px0 = float(rows.iloc[i]["close"])
        px1 = float(rows.iloc[i + horizon]["close"])
        raw = (px1 / max(px0, 1e-9)) - 1.0
        pnl = raw if signal["side"] == "buy" else -raw
        pnl -= 0.0011

        returns.append(float(pnl))
        trade_count += 1

    if returns:
        series = pd.Series(returns, dtype=float)
        wins = series[series > 0.0].sum()
        losses = abs(series[series < 0.0].sum())
        pf = float(wins / losses) if losses > 0 else 10.0
        mean = float(series.mean())
        std = float(series.std())
        bars_per_year = _bars_per_year(args.interval)
        sharpe = float((mean / std) * math.sqrt(bars_per_year)) if std > 1e-12 else 0.0
        eq = (1.0 + series).cumprod()
        peak = eq.cummax()
        mdd = float((1.0 - (eq / peak)).max()) if len(eq) else 0.0
    else:
        pf = 0.0
        sharpe = 0.0
        mdd = 0.0
        mean = 0.0

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": args.symbol,
        "period": args.period,
        "interval": args.interval,
        "registry": args.registry,
        "period_pf": pf,
        "period_sharpe": sharpe,
        "max_drawdown": mdd,
        "trade_count": int(trade_count),
        "expectancy": mean,
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "shadow_performance.json"
    target.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"shadow_artifact={target}")


if __name__ == "__main__":
    main()
