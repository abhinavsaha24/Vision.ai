from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.src.research.alpha_validation import AlphaValidationEngine
from backend.src.platform.market_context import MarketContextFetcher


def fetch_data(symbol: str, period: str, interval: str) -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval=interval, auto_adjust=False)
    if df is None or df.empty:
        raise RuntimeError("No data downloaded for validation")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(col[0]).lower().replace(" ", "_") for col in df.columns]
    else:
        df.columns = [str(col).lower().replace(" ", "_") for col in df.columns]
    df = df.rename(columns=str.lower)
    base = df[["open", "high", "low", "close", "volume"]].dropna().sort_index()
    return MarketContextFetcher().enrich_ohlcv(base, symbol=symbol, interval=interval)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTC-USD")
    parser.add_argument("--period", default="730d")
    parser.add_argument("--interval", default="1h")
    args = parser.parse_args()

    df = fetch_data(args.symbol, args.period, args.interval)
    engine = AlphaValidationEngine(fee_bps=6.0, slippage_bps=5.0)

    metrics, trade_returns, edge_report = engine.run_backtest_with_edge_report(df)
    flow_compare = engine.compare_with_without_flow(df)
    top_edges = engine.discover_top_edges(df, top_n=5)
    wf = engine.walk_forward(df, windows=6)
    mc = engine.monte_carlo(trade_returns, n_paths=3000)

    print("=== Backtest Metrics ===")
    print(metrics)
    print("=== Flow Ablation (WITH_FLOW vs WITHOUT_FLOW) ===")
    print(flow_compare)
    print("=== Edge Contribution Report ===")
    print(edge_report)
    print("=== Top 5 Discovered Edges ===")
    print(top_edges)
    print("=== Walk Forward ===")
    print(wf)
    print("=== Monte Carlo ===")
    print(mc)
    print("=== Targets Passed ===")
    print(engine.passes_targets(metrics))


if __name__ == "__main__":
    main()
