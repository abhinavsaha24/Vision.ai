"use client";

import { useMemo, useState } from "react";
import { apiService } from "@/services/api";
import { useMarketStore } from "@/store/marketStore";
import { TerminalCard } from "@/components/ui/terminal-card";

interface TradingPanelProps {
  onExecutionLog: (line: string) => void;
}

export function TradingPanel({ onExecutionLog }: TradingPanelProps) {
  const symbol = useMarketStore((state) => state.symbol);
  const signal = useMarketStore((state) => state.signal);
  const [sizeUsd, setSizeUsd] = useState(250);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const executionBias = useMemo(() => {
    if (!signal) return "NEUTRAL";
    if (signal.alpha_score >= 0.6 && signal.direction === "BUY")
      return "LONG BIAS";
    if (signal.alpha_score <= 0.4 && signal.direction === "SELL")
      return "SHORT BIAS";
    return "NEUTRAL";
  }, [signal]);

  async function execute(action: "buy" | "sell" | "close") {
    setSubmitting(true);
    setError(null);
    try {
      let response: unknown;
      if (action === "buy")
        response = await apiService.manualBuy(symbol, sizeUsd);
      if (action === "sell")
        response = await apiService.manualSell(symbol, sizeUsd);
      if (action === "close") response = await apiService.closePosition(symbol);
      onExecutionLog(
        `${new Date().toISOString()}  ${action.toUpperCase()} ${symbol}  ${JSON.stringify(response)}`,
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : "execution failed";
      setError(message);
      onExecutionLog(`${new Date().toISOString()}  ERROR ${message}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <TerminalCard
      title="Execution"
      right={<span className="text-xs text-cyan-300">{executionBias}</span>}
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3 text-xs text-slate-300">
          <div>
            <p className="mb-1 text-slate-500">Symbol</p>
            <p className="font-semibold">{symbol}</p>
          </div>
          <div>
            <p className="mb-1 text-slate-500">Alpha</p>
            <p className="font-semibold">
              {((signal?.alpha_score ?? 0.5) * 100).toFixed(1)}%
            </p>
          </div>
        </div>

        <div>
          <label className="mb-2 block text-xs uppercase tracking-[0.15em] text-slate-400">
            Position Size USD
          </label>
          <input
            type="number"
            min={10}
            value={sizeUsd}
            onChange={(event) => setSizeUsd(Number(event.target.value))}
            className="w-full rounded-lg border border-white/10 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none ring-cyan-500/50 transition focus:ring-2"
          />
        </div>

        <div className="grid grid-cols-3 gap-2">
          <button
            disabled={submitting}
            onClick={() => execute("buy")}
            className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm font-semibold text-emerald-300 transition hover:bg-emerald-500/20 disabled:opacity-50"
          >
            Buy
          </button>
          <button
            disabled={submitting}
            onClick={() => execute("sell")}
            className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm font-semibold text-rose-300 transition hover:bg-rose-500/20 disabled:opacity-50"
          >
            Sell
          </button>
          <button
            disabled={submitting}
            onClick={() => execute("close")}
            className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm font-semibold text-amber-200 transition hover:bg-amber-500/20 disabled:opacity-50"
          >
            Close
          </button>
        </div>

        {error ? <p className="text-xs text-rose-300">{error}</p> : null}
      </div>
    </TerminalCard>
  );
}
