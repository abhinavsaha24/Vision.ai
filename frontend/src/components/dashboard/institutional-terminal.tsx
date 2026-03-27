"use client";

import { useEffect, useMemo, useState, useCallback } from "react";
import { motion } from "framer-motion";
import { apiService, type Kline } from "@/services/api";
import {
  useMarketStore,
  type MarketSnapshot,
  type SignalSnapshot,
} from "@/store/marketStore";
import { usePortfolioStore } from "@/store/portfolioStore";
import { useTerminalWebSocket } from "@/hooks/useTerminalWebSocket";
import { MarketChart } from "@/components/charts/market-chart";
import { OrderbookPanel } from "@/components/dashboard/orderbook-panel";
import {
  TradeFlowPanel,
  type TradeEntry,
} from "@/components/dashboard/trade-flow-panel";
import {
  SignalPanel,
  type SignalEvent,
} from "@/components/dashboard/signal-panel";
import { EngineStatusPanel } from "@/components/dashboard/engine-status-panel";
import { TradingPanel } from "@/components/trading/trading-panel";
import { PortfolioPanel } from "@/components/dashboard/portfolio-panel";
import { RiskPanel } from "@/components/dashboard/risk-panel";
import {
  ActivityStream,
  type ActivityEvent,
} from "@/components/dashboard/activity-stream";
import { TerminalCard } from "@/components/ui/terminal-card";

const ASSETS = [
  "BTCUSDT",
  "ETHUSDT",
  "SOLUSDT",
  "BNBUSDT",
  "XRPUSDT",
  "DOGEUSDT",
];

/* ── Animated price ticker with tick flash ── */
function PriceTicker({
  value,
  prevValue,
  label,
}: {
  value: number | null;
  prevValue: number | null;
  label: string;
}) {
  const direction =
    value !== null && prevValue !== null
      ? value > prevValue
        ? "up"
        : value < prevValue
          ? "down"
          : "flat"
      : "flat";

  const flashClass =
    direction === "up"
      ? "tick-up"
      : direction === "down"
        ? "tick-down"
        : "";

  return (
    <div className="text-center">
      <span className="text-[10px] uppercase tracking-widest text-slate-500">
        {label}
      </span>
      <p
        key={value}
        className={`mt-0.5 font-mono text-sm font-semibold text-slate-100 ${flashClass}`}
      >
        {value !== null ? value.toFixed(2) : "--"}
      </p>
    </div>
  );
}

let activityIdCounter = 0;
function nextId(): string {
  return `act-${Date.now()}-${++activityIdCounter}`;
}

export function InstitutionalTerminal() {
  const symbol = useMarketStore((s) => s.symbol);
  const setSymbol = useMarketStore((s) => s.setSymbol);
  const market = useMarketStore((s) => s.market);
  const signal = useMarketStore((s) => s.signal);
  const updateMarket = useMarketStore((s) => s.updateMarket);
  const updateSignal = useMarketStore((s) => s.updateSignal);
  const updatePortfolio = usePortfolioStore((s) => s.updatePortfolio);
  const updateMetrics = usePortfolioStore((s) => s.updateMetrics);

  const [candles, setCandles] = useState<Kline[]>([]);
  const [trades, setTrades] = useState<TradeEntry[]>([]);
  const [signals, setSignals] = useState<SignalEvent[]>([]);
  const [activityEvents, setActivityEvents] = useState<ActivityEvent[]>([]);
  const [readiness, setReadiness] = useState<number | null>(null);
  const [liveClock, setLiveClock] = useState(() =>
    new Date().toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }),
  );

  // Track previous market values for tick animations
  const [prevMarket, setPrevMarket] = useState<MarketSnapshot | null>(null);

  const addActivity = useCallback(
    (type: ActivityEvent["type"], message: string, details?: string) => {
      const event: ActivityEvent = {
        id: nextId(),
        type,
        timestamp: new Date().toISOString(),
        message,
        details,
      };
      setActivityEvents((prev) => [...prev, event].slice(-200));
    },
    [],
  );

  const appendLog = useCallback(
    (line: string) => {
      addActivity("system", line);
    },
    [addActivity],
  );

  // WebSocket handlers
  const onMarket = useCallback(
    (data: unknown) => {
      const d = data as MarketSnapshot;
      setPrevMarket(market);
      updateMarket(d);

      // Extract trade from market update
      if (d.last_price && d.timestamp) {
        setTrades((prev) => {
          const entry: TradeEntry = {
            time: d.timestamp || new Date().toISOString(),
            price: d.last_price,
            size: Math.abs(d.volume_delta || 0.001),
            side: (d.volume_delta ?? 0) >= 0 ? "buy" : "sell",
            isLarge: Math.abs(d.volume_delta || 0) > 0.5,
          };
          return [...prev, entry].slice(-100);
        });
      }
    },
    [updateMarket, market],
  );

  const onSignal = useCallback(
    (data: unknown) => {
      const d = data as SignalSnapshot;
      updateSignal(d);
      const event: SignalEvent = {
        timestamp: d.timestamp || new Date().toISOString(),
        direction: d.direction,
        confidence: d.confidence,
        probability: d.probability,
        alpha_score: d.alpha_score,
        regime: d.regime,
        market_state: d.market_state,
        strategy: d.strategy,
      };
      setSignals((prev) => [...prev, event].slice(-50));
      addActivity(
        "signal",
        `${d.direction} signal (${(d.confidence * 100).toFixed(0)}%)`,
        `α=${d.alpha_score.toFixed(3)} regime=${d.regime}`,
      );
    },
    [updateSignal, addActivity],
  );

  const onPortfolio = useCallback(
    (data: unknown) => {
      updatePortfolio(data as never);
      addActivity("trade", "Portfolio update received");
    },
    [updatePortfolio, addActivity],
  );

  const onMetrics = useCallback(
    (data: unknown) => {
      updateMetrics(data as never);
    },
    [updateMetrics],
  );

  const wsState = useTerminalWebSocket(symbol, {
    onMarket,
    onSignal,
    onPortfolio,
    onMetrics,
  });

  // Fetch initial data
  useEffect(() => {
    let active = true;
    apiService
      .getMarketHistory(symbol, "1m", 300)
      .then((data) => {
        if (active) setCandles(data.candles ?? []);
      })
      .catch(() => {});

    apiService
      .getSystemReadiness()
      .then((data) => {
        if (active) {
          setReadiness(Number(data?.overall_score ?? data?.score ?? 0));
          addActivity("system", `Terminal initialized for ${symbol}`);
        }
      })
      .catch(() => {
        if (active) {
          setReadiness(null);
          addActivity("system", `Terminal initialized for ${symbol} (readiness unavailable)`);
        }
      });

    return () => {
      active = false;
    };
  }, [symbol, addActivity]);

  useEffect(() => {
    const timerId = window.setInterval(() => {
      setLiveClock(
        new Date().toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false,
        }),
      );
    }, 1000);

    return () => {
      window.clearInterval(timerId);
    };
  }, []);

  // Chart markers
  const markers = useMemo(() => {
    if (!signal || candles.length === 0) return [];
    const t = candles[candles.length - 1].time;
    if (signal.direction === "BUY") {
      return [
        {
          time: t,
          position: "belowBar" as const,
          color: "#10b981",
          text: "BUY",
        },
      ];
    }
    if (signal.direction === "SELL") {
      return [
        {
          time: t,
          position: "aboveBar" as const,
          color: "#f43f5e",
          text: "SELL",
        },
      ];
    }
    return [];
  }, [candles, signal]);

  const connectedCount = wsState.channels.filter((c) => c.connected).length;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="space-y-3"
    >
      {/* ═══════ HEADER BAR ═══════ */}
      <TerminalCard
        title="VISION AI — Institutional Terminal"
        right={
          <div className="flex items-center gap-3 text-xs">
            <span className="rounded-full border border-amber-400/30 bg-amber-500/10 px-2 py-1 font-mono text-amber-200">
              {liveClock}
            </span>
            <span
              className={`rounded-full px-2 py-1 font-mono ${
                connectedCount === 4
                  ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
                  : "bg-amber-500/15 text-amber-300 border border-amber-500/30"
              }`}
            >
              ⚡ {connectedCount}/4 LIVE
            </span>
            <span className="rounded-full border border-cyan-400/30 bg-cyan-500/10 px-2 py-1 font-mono text-cyan-200">
              SCORE {readiness !== null ? readiness.toFixed(0) : "--"}
            </span>
          </div>
        }
      >
        {/* Asset Selector */}
        <div className="mb-3 flex flex-wrap gap-2">
          {ASSETS.map((asset) => (
            <button
              key={asset}
              onClick={() => setSymbol(asset)}
              className={`rounded-lg border px-3 py-1.5 text-xs font-semibold tracking-wider transition ${
                symbol === asset
                  ? "border-cyan-400/50 bg-cyan-500/15 text-cyan-200 shadow-[0_0_15px_rgba(34,211,238,0.1)]"
                  : "border-white/8 bg-slate-900/50 text-slate-400 hover:border-cyan-400/30 hover:text-slate-200"
              }`}
            >
              {asset}
            </button>
          ))}
        </div>

        {/* Price Ticker Bar */}
        <div className="grid grid-cols-4 gap-4 rounded-lg border border-white/6 bg-slate-900/40 p-3">
          <PriceTicker
            value={market?.last_price ?? null}
            prevValue={prevMarket?.last_price ?? null}
            label="Last Price"
          />
          <PriceTicker
            value={market?.spread_bps ?? null}
            prevValue={prevMarket?.spread_bps ?? null}
            label="Spread BPS"
          />
          <PriceTicker
            value={market?.order_book_imbalance ?? null}
            prevValue={prevMarket?.order_book_imbalance ?? null}
            label="OB Imbalance"
          />
          <PriceTicker
            value={market?.volatility_expansion ?? null}
            prevValue={prevMarket?.volatility_expansion ?? null}
            label="Vol Expansion"
          />
        </div>
      </TerminalCard>

      {/* ═══════ MAIN GRID ═══════ */}
      <div className="grid gap-3 xl:grid-cols-12">
        {/* Left Column — 8/12 */}
        <div className="space-y-3 xl:col-span-8">
          {/* Chart */}
          <MarketChart candles={candles} markers={markers} />

          {/* Middle row: Orderbook + Trade Flow */}
          <div className="grid gap-3 lg:grid-cols-2">
            <OrderbookPanel
              bids={market?.bids ?? []}
              asks={market?.asks ?? []}
              lastPrice={market?.last_price ?? null}
              imbalance={market?.order_book_imbalance ?? null}
            />
            <TradeFlowPanel trades={trades} />
          </div>

          {/* Activity Stream (replaces simple log) */}
          <ActivityStream events={activityEvents} />
        </div>

        {/* Right Column — 4/12 */}
        <div className="space-y-3 xl:col-span-4">
          <SignalPanel
            signals={signals}
            currentSignal={
              signal
                ? {
                    timestamp: signal.timestamp,
                    direction: signal.direction,
                    confidence: signal.confidence,
                    probability: signal.probability,
                    alpha_score: signal.alpha_score,
                    regime: signal.regime,
                    strategy: signal.strategy,
                  }
                : null
            }
          />
          <RiskPanel />
          <TradingPanel onExecutionLog={appendLog} />
          <PortfolioPanel />
          <EngineStatusPanel
            channels={wsState.channels}
            reconnectCount={wsState.reconnectCount}
            lastLatencyMs={wsState.lastLatencyMs}
            messagesReceived={wsState.messagesReceived}
            uptime={wsState.uptime}
          />
        </div>
      </div>
    </motion.div>
  );
}
