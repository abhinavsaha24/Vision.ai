"use client";

import { memo, useRef, useCallback } from "react";
import { TerminalCard } from "@/components/ui/terminal-card";

export interface TradeEntry {
  time: string;
  price: number;
  size: number;
  side: "buy" | "sell";
  isLarge?: boolean;
}

interface TradeFlowPanelProps {
  trades: TradeEntry[];
}

const MAX_TRADES = 40;

function TradeFlowPanelInner({ trades }: TradeFlowPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  const formatTime = useCallback((ts: string) => {
    try {
      const d = new Date(ts);
      return d.toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } catch {
      return ts;
    }
  }, []);

  const displayTrades = trades.slice(-MAX_TRADES);

  return (
    <TerminalCard
      title="Trade Flow"
      right={
        <span className="font-mono text-[10px] text-slate-500">
          {trades.length} trades
        </span>
      }
    >
      <div ref={containerRef} className="max-h-64 overflow-auto space-y-0">
        {/* Header */}
        <div className="sticky top-0 z-10 grid grid-cols-4 bg-slate-950/90 pb-1 text-[10px] uppercase tracking-widest text-slate-500 border-b border-white/6">
          <span>Time</span>
          <span>Side</span>
          <span className="text-right">Price</span>
          <span className="text-right">Size</span>
        </div>

        {displayTrades.length === 0 && (
          <p className="py-6 text-center text-xs text-slate-600">Waiting for trades...</p>
        )}

        {[...displayTrades].reverse().map((trade, i) => (
          <div
            key={`trade-${i}`}
            className={`grid grid-cols-4 items-center py-[3px] text-[11px] font-mono border-b border-white/[0.03] ${
              trade.isLarge ? "bg-amber-500/5" : ""
            }`}
          >
            <span className="text-slate-500">{formatTime(trade.time)}</span>
            <span className={trade.side === "buy" ? "text-emerald-400" : "text-rose-400"}>
              {trade.side === "buy" ? "▲ BUY" : "▼ SELL"}
            </span>
            <span className="text-right text-slate-200">{trade.price.toFixed(2)}</span>
            <span className={`text-right ${trade.isLarge ? "text-amber-300 font-semibold" : "text-slate-400"}`}>
              {trade.size.toFixed(4)}
            </span>
          </div>
        ))}
      </div>
    </TerminalCard>
  );
}

export const TradeFlowPanel = memo(TradeFlowPanelInner);
