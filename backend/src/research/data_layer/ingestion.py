from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from .schema import (
    CROSS_ASSET_CLOSE,
    DERIV_BASIS,
    DERIV_FUNDING,
    DERIV_OPEN_INTEREST,
    EVENT_LIQUIDATIONS,
    EVENT_VOL_SHOCK,
    MICRO_ORDERBOOK,
    MICRO_TRADES,
    SourceConfig,
)
from .storage import TimeSeriesStore


def collect_all_sources(store: TimeSeriesStore, config: SourceConfig, cross_assets: list[str]) -> dict:
    stats: dict[str, int] = {}

    micro_book = _ingest_orderbook_proxy(config)
    stats[MICRO_ORDERBOOK] = store.upsert_frame(micro_book, MICRO_ORDERBOOK, config.symbol)

    trades = _ingest_trade_prints(config)
    stats[MICRO_TRADES] = store.upsert_frame(trades, MICRO_TRADES, config.symbol)

    funding = _ingest_funding_rates(config.symbol, config.lookback_hours)
    stats[DERIV_FUNDING] = store.upsert_frame(funding, DERIV_FUNDING, config.symbol)

    oi = _ingest_open_interest(config.symbol, config.lookback_hours)
    stats[DERIV_OPEN_INTEREST] = store.upsert_frame(oi, DERIV_OPEN_INTEREST, config.symbol)

    basis = _ingest_perp_spot_basis(config)
    stats[DERIV_BASIS] = store.upsert_frame(basis, DERIV_BASIS, config.symbol)

    liq = _ingest_liquidations(config.symbol, config.lookback_hours)
    stats[EVENT_LIQUIDATIONS] = store.upsert_frame(liq, EVENT_LIQUIDATIONS, config.symbol)

    vol_shock = _ingest_volatility_shocks(config)
    stats[EVENT_VOL_SHOCK] = store.upsert_frame(vol_shock, EVENT_VOL_SHOCK, config.symbol)

    for asset in cross_assets:
        cross = _ingest_cross_asset(asset, config)
        stats[f"{CROSS_ASSET_CLOSE}:{asset}"] = store.upsert_frame(cross, CROSS_ASSET_CLOSE, asset)

    return stats


def _ingest_orderbook_proxy(config: SourceConfig) -> pd.DataFrame:
    # Public REST snapshots are sparse; emulate aligned L2 depth states from recent klines and intrabar spread proxy.
    klines = _binance_klines(config.symbol, config.interval, config.lookback_hours)
    if klines.empty:
        return pd.DataFrame(columns=["ts", "value", "v1", "v2", "v3", "v4", "meta"])
    spread_proxy = (klines["high"] - klines["low"]) / (klines["close"].replace(0.0, np.nan) + 1e-12)
    depth_bid = (1.0 / (spread_proxy + 1e-6)).clip(upper=2000.0)
    depth_ask = (1.0 / (spread_proxy + 1e-6)).clip(upper=2000.0) * (1.0 + klines["ret"].fillna(0.0))

    out = pd.DataFrame(
        {
            "ts": klines["ts"],
            "value": (depth_bid - depth_ask),
            "v1": depth_bid,
            "v2": depth_ask,
            "v3": spread_proxy.fillna(0.0),
            "v4": klines["volume"],
            "meta": "book_proxy",
        }
    )
    return out


def _ingest_trade_prints(config: SourceConfig) -> pd.DataFrame:
    agg = _binance_agg_trades(config.symbol, config.lookback_hours)
    if agg.empty:
        return pd.DataFrame(columns=["ts", "value", "v1", "v2", "v3", "v4", "meta"])

    agg["signed_qty"] = np.where(agg["is_buyer_maker"], -agg["qty"], agg["qty"])
    grp = agg.groupby("ts", as_index=False).agg(
        signed_flow=("signed_qty", "sum"),
        total_qty=("qty", "sum"),
        trade_count=("qty", "count"),
        mean_price=("price", "mean"),
    )
    grp["aggressor_imbalance"] = grp["signed_flow"] / (grp["total_qty"].replace(0.0, np.nan) + 1e-12)
    return pd.DataFrame(
        {
            "ts": grp["ts"],
            "value": grp["signed_flow"],
            "v1": grp["aggressor_imbalance"].fillna(0.0),
            "v2": grp["total_qty"],
            "v3": grp["trade_count"],
            "v4": grp["mean_price"],
            "meta": "agg_trade_flow",
        }
    )


def _ingest_funding_rates(symbol: str, lookback_hours: int) -> pd.DataFrame:
    url = "https://fapi.binance.com/fapi/v1/fundingRate"
    params = {"symbol": _to_binance_symbol(symbol), "limit": min(1000, max(100, lookback_hours // 8 + 5))}
    data = _safe_get(url, params)
    if not data:
        return pd.DataFrame(columns=["ts", "value", "v1", "v2", "v3", "v4", "meta"])
    df = pd.DataFrame(data)
    df["ts"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True).dt.floor("h").astype(str)
    return pd.DataFrame(
        {
            "ts": df["ts"],
            "value": pd.to_numeric(df["fundingRate"], errors="coerce").fillna(0.0),
            "v1": 0.0,
            "v2": 0.0,
            "v3": 0.0,
            "v4": 0.0,
            "meta": "funding",
        }
    )


def _ingest_open_interest(symbol: str, lookback_hours: int) -> pd.DataFrame:
    url = "https://fapi.binance.com/futures/data/openInterestHist"
    params = {
        "symbol": _to_binance_symbol(symbol),
        "period": "1h",
        "limit": min(500, max(50, lookback_hours)),
    }
    data = _safe_get(url, params)
    if not data:
        return pd.DataFrame(columns=["ts", "value", "v1", "v2", "v3", "v4", "meta"])
    df = pd.DataFrame(data)
    df["ts"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.floor("h").astype(str)
    oi = pd.to_numeric(df["sumOpenInterest"], errors="coerce").fillna(0.0)
    oi_value_col = df["sumOpenInterestValue"] if "sumOpenInterestValue" in df.columns else pd.Series(0.0, index=df.index)
    oi_value = pd.to_numeric(oi_value_col, errors="coerce").fillna(0.0)
    return pd.DataFrame(
        {
            "ts": df["ts"],
            "value": oi,
            "v1": oi.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0),
            "v2": oi_value,
            "v3": 0.0,
            "v4": 0.0,
            "meta": "open_interest",
        }
    )


def _ingest_perp_spot_basis(config: SourceConfig) -> pd.DataFrame:
    klines = _binance_klines(config.symbol, config.interval, config.lookback_hours)
    if klines.empty:
        return pd.DataFrame(columns=["ts", "value", "v1", "v2", "v3", "v4", "meta"])
    ticker = yf.download(config.symbol, period=f"{max(10, config.lookback_hours // 24 + 5)}d", interval=config.interval, auto_adjust=False)
    if ticker is None or ticker.empty:
        return pd.DataFrame(columns=["ts", "value", "v1", "v2", "v3", "v4", "meta"])
    if isinstance(ticker.columns, pd.MultiIndex):
        ticker.columns = [str(c[0]).lower() for c in ticker.columns]
    else:
        ticker.columns = [str(c).lower() for c in ticker.columns]
    spot = ticker[["close"]].copy()
    spot.index = pd.to_datetime(spot.index, utc=True).floor("h")
    spot = spot.rename(columns={"close": "spot_close"})

    perp = klines.copy()
    perp.index = pd.to_datetime(perp["ts"], utc=True)
    merged = perp.join(spot, how="inner")
    if merged.empty:
        return pd.DataFrame(columns=["ts", "value", "v1", "v2", "v3", "v4", "meta"])

    basis = (merged["close"] - merged["spot_close"]) / (merged["spot_close"] + 1e-12)
    return pd.DataFrame(
        {
            "ts": merged.index.astype(str),
            "value": basis,
            "v1": merged["close"],
            "v2": merged["spot_close"],
            "v3": merged["volume"],
            "v4": 0.0,
            "meta": "perp_spot_basis",
        }
    )


def _ingest_liquidations(symbol: str, lookback_hours: int) -> pd.DataFrame:
    # Binance public liquidation endpoint is recent-window oriented; aggregate as hourly pressure.
    url = "https://fapi.binance.com/fapi/v1/allForceOrders"
    start = int((datetime.now(UTC) - timedelta(hours=lookback_hours)).timestamp() * 1000)
    params = {"symbol": _to_binance_symbol(symbol), "startTime": start, "limit": 1000}
    data = _safe_get(url, params)
    if not data:
        return pd.DataFrame(columns=["ts", "value", "v1", "v2", "v3", "v4", "meta"])
    df = pd.DataFrame(data)
    qty_col = df["origQty"] if "origQty" in df.columns else pd.Series(0.0, index=df.index)
    px_col = df["avgPrice"] if "avgPrice" in df.columns else pd.Series(0.0, index=df.index)
    side_col = df["side"] if "side" in df.columns else pd.Series("SELL", index=df.index)
    qty = pd.to_numeric(qty_col, errors="coerce").fillna(0.0)
    px = pd.to_numeric(px_col, errors="coerce").fillna(0.0)
    side = np.where(side_col.astype(str) == "SELL", -1.0, 1.0)
    notional = qty * px * side
    ts = pd.to_datetime(df["time"], unit="ms", utc=True).dt.floor("h")
    grp = pd.DataFrame({"ts": ts.astype(str), "notional": notional, "count": 1}).groupby("ts", as_index=False).agg(
        liq_pressure=("notional", "sum"),
        liq_count=("count", "sum"),
    )
    return pd.DataFrame(
        {
            "ts": grp["ts"],
            "value": grp["liq_pressure"],
            "v1": grp["liq_count"],
            "v2": grp["liq_pressure"].abs(),
            "v3": 0.0,
            "v4": 0.0,
            "meta": "liquidations",
        }
    )


def _ingest_volatility_shocks(config: SourceConfig) -> pd.DataFrame:
    klines = _binance_klines(config.symbol, config.interval, config.lookback_hours)
    if klines.empty:
        return pd.DataFrame(columns=["ts", "value", "v1", "v2", "v3", "v4", "meta"])

    ret = klines["close"].pct_change().fillna(0.0)
    vol = ret.rolling(24, min_periods=8).std().fillna(0.0)
    z = ((vol - vol.rolling(72, min_periods=24).mean()) / (vol.rolling(72, min_periods=24).std() + 1e-12)).fillna(0.0)
    shock = (z > 2.0).astype(float)
    return pd.DataFrame(
        {
            "ts": klines["ts"],
            "value": z,
            "v1": shock,
            "v2": vol,
            "v3": ret,
            "v4": klines["volume"],
            "meta": "vol_shock",
        }
    )


def _ingest_cross_asset(asset: str, config: SourceConfig) -> pd.DataFrame:
    yf_symbol = _to_yf_symbol(asset)
    df = yf.download(yf_symbol, period=f"{max(10, config.lookback_hours // 24 + 5)}d", interval=config.interval, auto_adjust=False)
    if df is None or df.empty:
        return pd.DataFrame(columns=["ts", "value", "v1", "v2", "v3", "v4", "meta"])
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]).lower() for c in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]
    idx = pd.to_datetime(df.index, utc=True).floor("h")
    close = pd.to_numeric(df["close"], errors="coerce").ffill()
    out = pd.DataFrame(
        {
            "ts": idx.astype(str),
            "value": close.values,
            "v1": close.pct_change().fillna(0.0).values,
            "v2": pd.to_numeric(df["volume"], errors="coerce").fillna(0.0).values if "volume" in df.columns else 0.0,
            "v3": 0.0,
            "v4": 0.0,
            "meta": "cross_asset_close",
        }
    )
    return out


def _binance_klines(symbol: str, interval: str, lookback_hours: int) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"
    start = int((datetime.now(UTC) - timedelta(hours=lookback_hours)).timestamp() * 1000)
    params = {"symbol": _to_binance_symbol(symbol), "interval": interval, "startTime": start, "limit": 1000}
    data = _safe_get(url, params)
    if not data:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume", "ret"])
    df = pd.DataFrame(data)
    out = pd.DataFrame(
        {
            "ts": pd.to_datetime(df[0], unit="ms", utc=True).dt.floor("h").astype(str),
            "open": pd.to_numeric(df[1], errors="coerce"),
            "high": pd.to_numeric(df[2], errors="coerce"),
            "low": pd.to_numeric(df[3], errors="coerce"),
            "close": pd.to_numeric(df[4], errors="coerce"),
            "volume": pd.to_numeric(df[5], errors="coerce"),
        }
    )
    out["ret"] = out["close"].pct_change().fillna(0.0)
    return out.dropna().copy()


def _binance_agg_trades(symbol: str, lookback_hours: int) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/aggTrades"
    start = int((datetime.now(UTC) - timedelta(hours=lookback_hours)).timestamp() * 1000)
    params = {"symbol": _to_binance_symbol(symbol), "startTime": start, "limit": 1000}
    data = _safe_get(url, params)
    if not data:
        return pd.DataFrame(columns=["ts", "price", "qty", "is_buyer_maker"])
    df = pd.DataFrame(data)
    return pd.DataFrame(
        {
            "ts": pd.to_datetime(df["T"], unit="ms", utc=True).dt.floor("h").astype(str),
            "price": pd.to_numeric(df["p"], errors="coerce").fillna(0.0),
            "qty": pd.to_numeric(df["q"], errors="coerce").fillna(0.0),
            "is_buyer_maker": df["m"].astype(bool),
        }
    )


def _safe_get(url: str, params: dict) -> list | dict | None:
    try:
        resp = requests.get(url, params=params, timeout=20)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


def _to_binance_symbol(symbol: str) -> str:
    s = symbol.upper().replace("-", "")
    if s.endswith("USD") and not s.endswith("USDT"):
        s = s.replace("USD", "USDT")
    return s


def _to_yf_symbol(asset: str) -> str:
    m = {
        "BTC-USD": "BTC-USD",
        "ETH-USD": "ETH-USD",
        "SPX": "^GSPC",
        "NDX": "^NDX",
        "QQQ": "QQQ",
    }
    return m.get(asset.upper(), asset)
