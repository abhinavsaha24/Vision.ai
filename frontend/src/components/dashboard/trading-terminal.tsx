"use client";

import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { apiService, Kline } from "@/services/api";
import { createRealtimeChannel } from "@/services/websocket";
import { useMarketStore } from "@/store/marketStore";
import { usePortfolioStore } from "@/store/portfolioStore";
import { MarketChart } from "@/components/charts/market-chart";
import { TradingPanel } from "@/components/trading/trading-panel";
import { AlphaPanel } from "@/components/dashboard/alpha-panel";
import { PortfolioPanel } from "@/components/dashboard/portfolio-panel";
import { LiveFeedPanel } from "@/components/dashboard/live-feed-panel";
import { TerminalCard } from "@/components/ui/terminal-card";

function useRealtimeTerminal(
  symbol: string,
  appendLog: (line: string) => void,
) {
  const updateMarket = useMarketStore((state) => state.updateMarket);
  const updateSignal = useMarketStore((state) => state.updateSignal);
  const updatePortfolio = usePortfolioStore((state) => state.updatePortfolio);
  const updateMetrics = usePortfolioStore((state) => state.updateMetrics);
  const [connection, setConnection] = useState({
    market: false,
    signal: false,
    portfolio: false,
    metrics: false,
  });

  useEffect(() => {
    const marketChannel = createRealtimeChannel({ channel: "market", symbol });
    const signalChannel = createRealtimeChannel({ channel: "signals", symbol });
    const portfolioChannel = createRealtimeChannel({ channel: "portfolio" });
    const metricsChannel = createRealtimeChannel({ channel: "metrics" });

    const unsubs = [
      marketChannel.subscribe((payload) => {
        updateMarket(payload as never);
        appendLog(
          `${new Date().toISOString()}  MARKET ${JSON.stringify(payload)}`,
        );
      }),
      signalChannel.subscribe((payload) => {
        updateSignal(payload as never);
        appendLog(
          `${new Date().toISOString()}  SIGNAL ${JSON.stringify(payload)}`,
        );
      }),
      portfolioChannel.subscribe((payload) => {
        updatePortfolio(payload as never);
      }),
      metricsChannel.subscribe((payload) => {
        updateMetrics(payload as never);
      }),
      marketChannel.subscribeStatus((connected) =>
        setConnection((s) => ({ ...s, market: connected })),
      ),
      signalChannel.subscribeStatus((connected) =>
        setConnection((s) => ({ ...s, signal: connected })),
      ),
      portfolioChannel.subscribeStatus((connected) =>
        setConnection((s) => ({ ...s, portfolio: connected })),
      ),
      metricsChannel.subscribeStatus((connected) =>
        setConnection((s) => ({ ...s, metrics: connected })),
      ),
    ];

    marketChannel.start();
    signalChannel.start();
    portfolioChannel.start();
    metricsChannel.start();

    return () => {
      unsubs.forEach((unsub) => unsub());
      marketChannel.stop();
      signalChannel.stop();
      portfolioChannel.stop();
      metricsChannel.stop();
    };
  }, [
    appendLog,
    symbol,
    updateMarket,
    updateMetrics,
    updatePortfolio,
    updateSignal,
  ]);

  return connection;
}

export function TradingTerminal() {
  const symbol = useMarketStore((state) => state.symbol);
  const setSymbol = useMarketStore((state) => state.setSymbol);
  const signal = useMarketStore((state) => state.signal);
  const market = useMarketStore((state) => state.market);

  const [candles, setCandles] = useState<Kline[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const [readiness, setReadiness] = useState<number | null>(null);

  const appendLog = (line: string) => {
    setLogs((prev) => [...prev, line].slice(-300));
  };

  const connection = useRealtimeTerminal(symbol, appendLog);

  useEffect(() => {
    let active = true;
    apiService
      .getMarketHistory(symbol, "1m", 300)
      .then((data) => {
        if (active) setCandles(data.candles ?? []);
      })
      .catch((err) =>
        appendLog(`${new Date().toISOString()}  ERROR history ${String(err)}`),
      );

    apiService
      .getSystemReadiness()
      .then((data) => {
        if (active)
          setReadiness(Number(data?.overall_score ?? data?.score ?? 0));
      })
      .catch(() => {
        if (active) setReadiness(null);
      });

    return () => {
      active = false;
    };
  }, [symbol]);

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

  const connectedCount = Object.values(connection).filter(Boolean).length;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="space-y-4"
    >
      <TerminalCard
        title="Vision AI Institutional Terminal"
        right={
          <div className="flex items-center gap-3 text-xs text-slate-300">
            <span
              className={`rounded-full px-2 py-1 ${connectedCount === 4 ? "bg-emerald-500/20 text-emerald-300" : "bg-amber-500/20 text-amber-300"}`}
            >
              Streams {connectedCount}/4
            </span>
            <span className="rounded-full bg-cyan-500/20 px-2 py-1 text-cyan-200">
              Readiness {readiness !== null ? readiness.toFixed(1) : "--"}
            </span>
          </div>
        }
      >
        <div className="grid gap-3 md:grid-cols-4">
          {["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"].map((asset) => (
            <button
              key={asset}
              onClick={() => setSymbol(asset)}
              className={`rounded-lg border px-3 py-2 text-sm font-semibold transition ${symbol === asset ? "border-cyan-400/70 bg-cyan-500/10 text-cyan-200" : "border-white/10 bg-slate-900/70 text-slate-300 hover:border-cyan-500/50"}`}
            >
              {asset}
            </button>
          ))}
        </div>
        <div className="mt-3 grid gap-3 md:grid-cols-4 text-xs text-slate-400">
          <p>
            Last Price:{" "}
            <span className="text-slate-100">
              {market?.last_price?.toFixed(2) ?? "--"}
            </span>
          </p>
          <p>
            Spread Bps:{" "}
            <span className="text-slate-100">
              {market?.spread_bps?.toFixed(2) ?? "--"}
            </span>
          </p>
          <p>
            OB Imbalance:{" "}
            <span className="text-slate-100">
              {market?.order_book_imbalance?.toFixed(3) ?? "--"}
            </span>
          </p>
          <p>
            Vol Expansion:{" "}
            <span className="text-slate-100">
              {market?.volatility_expansion?.toFixed(3) ?? "--"}
            </span>
          </p>
        </div>
      </TerminalCard>

      <div className="grid gap-4 xl:grid-cols-12">
        <div className="xl:col-span-8 space-y-4">
          <MarketChart candles={candles} markers={markers} />
          <LiveFeedPanel lines={logs} />
        </div>
        <div className="xl:col-span-4 space-y-4">
          <TradingPanel onExecutionLog={appendLog} />
          <AlphaPanel />
          <PortfolioPanel />
        </div>
      </div>
    </motion.div>
  );
}
