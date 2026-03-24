from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf
from pandas.tseries.frequencies import to_offset

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.src.platform.market_context import MarketContextFetcher
from backend.src.data.binance_trades import BinanceTradesClient


def _to_binance_symbol(symbol: str) -> str:
    s = str(symbol).upper().replace("/", "").replace("-", "")
    if s.endswith("USD") and not s.endswith("USDT"):
        s = s[:-3] + "USDT"
    return s


def _normalize_interval(interval: str) -> str:
    try:
        return to_offset(str(interval).strip()).freqstr.lower()
    except ValueError as exc:
        raise ValueError(f"invalid interval '{interval}': {exc}") from exc


def _optimize_trade_dtypes(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades
    out = trades.copy()
    for col in ["price", "qty", "direction", "signed_volume", "notional"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0).astype("float32")
    if "trade_id" in out.columns:
        out["trade_id"] = pd.to_numeric(out["trade_id"], errors="coerce").fillna(-1).astype("int64")
    if "is_buyer_maker" in out.columns:
        out["is_buyer_maker"] = out["is_buyer_maker"].astype(bool)
    if "ts" in out.columns:
        out["ts"] = pd.to_datetime(out["ts"], utc=True)
    return out


def _fetch_price(symbol: str, period: str, interval: str) -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval=interval, auto_adjust=False)
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(col[0]).lower() for col in df.columns]
    else:
        df.columns = [str(col).lower() for col in df.columns]
    out = df[["open", "high", "low", "close", "volume"]].dropna().sort_index()
    out.index = pd.to_datetime(out.index, utc=True)
    return out


def _with_ts_column(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    if "Datetime" in frame.columns and str(frame.index.name or "") == "Datetime":
        frame = frame.drop(columns=["Datetime"])
    idx_name = str(frame.index.name or "index")
    out = frame.reset_index()
    out = out.rename(columns={idx_name: "ts", "index": "ts"})
    if "ts" not in out.columns and len(out.columns) > 0:
        out = out.rename(columns={out.columns[0]: "ts"})
    return out


def _fetch_trades_resumable(
    trades_client: BinanceTradesClient,
    symbol: str,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    existing_path: Path,
    use_resume: bool,
    max_trade_rows: int,
) -> pd.DataFrame:
    start = pd.Timestamp(start_ts)
    end = pd.Timestamp(end_ts)
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    else:
        start = start.tz_convert("UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    else:
        end = end.tz_convert("UTC")
    existing = pd.DataFrame()

    if use_resume and existing_path.exists():
        try:
            existing = pd.read_parquet(existing_path)
            if not existing.empty and "ts" in existing.columns:
                existing["ts"] = pd.to_datetime(existing["ts"], utc=True)
                last_ts = pd.Timestamp(existing["ts"].max()).tz_convert("UTC")
                start = max(start, last_ts + pd.Timedelta(milliseconds=1))
            existing = _optimize_trade_dtypes(existing)
        except Exception:
            existing = pd.DataFrame()

    if start >= end:
        if existing.empty:
            return pd.DataFrame()
        return existing.sort_values("ts").drop_duplicates(subset=["trade_id"], keep="last").reset_index(drop=True)

    day_cursor = start.floor("D")
    merged = existing.copy() if not existing.empty else pd.DataFrame()
    pending_chunks: list[pd.DataFrame] = []

    def _flush_pending() -> None:
        nonlocal merged, pending_chunks
        if not pending_chunks:
            return
        incoming = pd.concat(pending_chunks, axis=0, ignore_index=True)
        pending_chunks = []
        incoming = _optimize_trade_dtypes(incoming)
        merged = incoming if merged.empty else pd.concat([merged, incoming], axis=0, ignore_index=True)
        merged["ts"] = pd.to_datetime(merged["ts"], utc=True)
        merged = merged.sort_values("ts").drop_duplicates(subset=["trade_id"], keep="last")
        if max_trade_rows > 0 and len(merged) > max_trade_rows:
            merged = merged.tail(max_trade_rows)
        merged = _optimize_trade_dtypes(merged).reset_index(drop=True)

    while day_cursor <= end.floor("D"):
        day_start = max(start, day_cursor)
        day_end = min(end, day_cursor + timedelta(days=1) - timedelta(milliseconds=1))
        if day_start <= day_end:
            day_df = trades_client.fetch_agg_trades(
                symbol=symbol,
                start_time_ms=int(day_start.timestamp() * 1000),
                end_time_ms=int(day_end.timestamp() * 1000),
            )
            if not day_df.empty:
                pending_chunks.append(day_df)
                if len(pending_chunks) >= 7:
                    _flush_pending()
        day_cursor = day_cursor + timedelta(days=1)

    _flush_pending()

    if merged.empty:
        return pd.DataFrame()

    merged["ts"] = pd.to_datetime(merged["ts"], utc=True)
    merged = merged.sort_values("ts").drop_duplicates(subset=["trade_id"], keep="last")
    if max_trade_rows > 0 and len(merged) > max_trade_rows:
        merged = merged.tail(max_trade_rows)
    return _optimize_trade_dtypes(merged).reset_index(drop=True)


def _trade_coverage_audit(price: pd.DataFrame, trades: pd.DataFrame, interval: str) -> dict[str, float]:
    price_hours = pd.DatetimeIndex(pd.to_datetime(price.index, utc=True)).floor(interval)
    if len(price_hours) == 0:
        return {
            "expected_bars": 0.0,
            "bars_with_trades": 0.0,
            "coverage_ratio": 0.0,
            "trade_rows": 0.0,
        }
    expected = int(price_hours.nunique())
    if trades.empty:
        return {
            "expected_bars": float(expected),
            "bars_with_trades": 0.0,
            "coverage_ratio": 0.0,
            "trade_rows": 0.0,
        }

    t = trades.copy()
    t["ts"] = pd.to_datetime(t["ts"], utc=True)
    trade_hours = pd.DatetimeIndex(t["ts"]).floor(interval)
    bars_with_trades = int(pd.Index(price_hours.unique()).intersection(pd.Index(trade_hours.unique())).shape[0])
    ratio = float(bars_with_trades / max(expected, 1))
    return {
        "expected_bars": float(expected),
        "bars_with_trades": float(bars_with_trades),
        "coverage_ratio": ratio,
        "trade_rows": float(len(t)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect and persist flow/context datasets for research")
    parser.add_argument("--symbols", nargs="+", default=["BTC-USD", "ETH-USD", "SOL-USD"])
    parser.add_argument("--period", default="730d")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--output-dir", default="data/flow")
    parser.add_argument("--research-dir", default="data/research")
    parser.add_argument("--trade-dir", default="data/trades")
    parser.add_argument("--coverage-report", default="data/trade_coverage_report.json")
    parser.add_argument("--resume-trades", action="store_true")
    parser.add_argument("--enforce-trade-window", action="store_true")
    parser.add_argument("--max-trade-rows", type=int, default=1_500_000)
    args = parser.parse_args()
    interval = _normalize_interval(args.interval)

    out_dir = Path(args.output_dir)
    research_dir = Path(args.research_dir)
    trade_dir = Path(args.trade_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    research_dir.mkdir(parents=True, exist_ok=True)
    trade_dir.mkdir(parents=True, exist_ok=True)
    fetcher = MarketContextFetcher()
    trades_client = BinanceTradesClient()

    flow_columns = [
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
    ]
    coverage_report: dict[str, dict[str, float | str]] = {}

    for symbol in args.symbols:
        price = _fetch_price(symbol=symbol, period=args.period, interval=args.interval)
        if price.empty:
            print(f"skip {symbol}: no_price_data")
            continue

        enriched = fetcher.enrich_ohlcv(price, symbol=symbol, interval=args.interval)
        if enriched.empty:
            print(f"skip {symbol}: no_enriched_data")
            continue

        # Persist raw trade-level data and merge execution features into research frame.
        try:
            trade_target = trade_dir / f"{_to_binance_symbol(symbol)}_aggtrades.parquet"
            trades = _fetch_trades_resumable(
                trades_client=trades_client,
                symbol=symbol,
                start_ts=pd.to_datetime(price.index.min(), utc=True),
                end_ts=pd.to_datetime(price.index.max(), utc=True),
                existing_path=trade_target,
                use_resume=bool(args.resume_trades),
                max_trade_rows=max(int(args.max_trade_rows), 0),
            )
            if not trades.empty:
                trades.to_parquet(trade_target, index=False)
                print(f"saved {symbol} -> {trade_target} rows={len(trades)}")

                cov = _trade_coverage_audit(price=price, trades=trades, interval=interval)
                coverage_report[symbol] = {
                    "symbol": symbol,
                    "trade_file": str(trade_target),
                    **cov,
                }
                print(
                    f"coverage {symbol}: bars={int(cov['bars_with_trades'])}/{int(cov['expected_bars'])} "
                    f"ratio={cov['coverage_ratio']:.3f}"
                )

                trade_feat = trades_client.build_execution_features(trades, interval=interval)
                if not trade_feat.empty:
                    trade_feat.index = pd.DatetimeIndex(pd.to_datetime(trade_feat.index, utc=True))
                    add_cols = [c for c in trade_feat.columns if c not in enriched.columns]
                    if add_cols:
                        enriched = enriched.join(trade_feat[add_cols], how="left")
                    enriched = enriched.ffill().fillna(0.0)

                if args.enforce_trade_window:
                    trade_ts = pd.to_datetime(trades["ts"], utc=True)
                    trade_start = trade_ts.min().floor(interval)
                    trade_end = trade_ts.max().ceil(interval)
                    enriched = enriched.loc[(enriched.index >= trade_start) & (enriched.index <= trade_end)].copy()
                    print(
                        f"trade_window {symbol}: start={trade_start} end={trade_end} rows={len(enriched)}"
                    )
        except Exception as exc:
            print(f"warn {symbol}: trade_fetch_failed err={exc}")
            coverage_report[symbol] = {
                "symbol": symbol,
                "trade_file": str(trade_dir / f"{_to_binance_symbol(symbol)}_aggtrades.parquet"),
                "error": str(exc),
            }

        trade_cols = [c for c in enriched.columns if str(c).startswith("trade_")]
        cols = [c for c in flow_columns if c in enriched.columns] + trade_cols
        flow_frame = _with_ts_column(enriched[cols].copy())

        target = out_dir / f"{_to_binance_symbol(symbol)}_{interval}.parquet"
        flow_frame.to_parquet(target, index=False)
        research_frame = _with_ts_column(enriched)
        research_target = research_dir / f"{_to_binance_symbol(symbol)}_{interval}.parquet"
        research_frame.to_parquet(research_target, index=False)
        print(f"saved {symbol} -> {target} rows={len(flow_frame)}")
        print(f"saved {symbol} -> {research_target} rows={len(research_frame)}")

    report_path = Path(args.coverage_report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(coverage_report, indent=2), encoding="utf-8")
    print(f"trade_coverage_report={report_path}")


if __name__ == "__main__":
    main()
