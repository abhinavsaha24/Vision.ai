"use client";

import { memo, useMemo } from "react";
import { motion } from "framer-motion";
import { TerminalCard } from "@/components/ui/terminal-card";

interface OrderbookPanelProps {
  bids: [number, number][];
  asks: [number, number][];
  lastPrice: number | null;
  imbalance: number | null;
}

const MAX_ROWS = 14;

/* ── Heatmap intensity helper ── */
function heatColor(pct: number, side: "bid" | "ask"): string {
  // Higher volume = more intense color
  const intensity = Math.min(pct / 100, 1);
  if (side === "bid") {
    const alpha = (0.04 + intensity * 0.22).toFixed(2);
    return `rgba(16, 185, 129, ${alpha})`; // emerald
  }
  const alpha = (0.04 + intensity * 0.22).toFixed(2);
  return `rgba(244, 63, 94, ${alpha})`; // rose
}

function OrderbookPanelInner({
  bids,
  asks,
  lastPrice,
  imbalance,
}: OrderbookPanelProps) {
  const { displayBids, displayAsks, maxQty, bidVolume, askVolume } =
    useMemo(() => {
      const sortedBids = [...bids]
        .sort((a, b) => b[0] - a[0])
        .slice(0, MAX_ROWS);
      const sortedAsks = [...asks]
        .sort((a, b) => a[0] - b[0])
        .slice(0, MAX_ROWS);
      const allQtys = [...sortedBids, ...sortedAsks].map((l) => l[1]);
      const max = Math.max(...allQtys, 1);
      const bidVol = sortedBids.reduce((sum, [, q]) => sum + q, 0);
      const askVol = sortedAsks.reduce((sum, [, q]) => sum + q, 0);
      return {
        displayBids: sortedBids,
        displayAsks: sortedAsks,
        maxQty: max,
        bidVolume: bidVol,
        askVolume: askVol,
      };
    }, [bids, asks]);

  const imbalanceColor =
    imbalance === null
      ? "text-slate-400"
      : imbalance > 0.1
        ? "text-emerald-400"
        : imbalance < -0.1
          ? "text-rose-400"
          : "text-slate-300";

  // Imbalance bar ratio
  const totalVol = bidVolume + askVolume;
  const bidPct = totalVol > 0 ? (bidVolume / totalVol) * 100 : 50;

  return (
    <TerminalCard
      title="Order Book"
      right={
        <div className="flex items-center gap-2">
          <span className={`font-mono text-xs ${imbalanceColor}`}>
            IMB{" "}
            {imbalance !== null
              ? (imbalance > 0 ? "+" : "") + imbalance.toFixed(3)
              : "--"}
          </span>
        </div>
      }
    >
      <div className="space-y-0.5 text-[11px] font-mono">
        {/* Imbalance bar */}
        <div className="mb-2 flex h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
          <motion.div
            className="h-full bg-gradient-to-r from-emerald-600 to-emerald-400"
            animate={{ width: `${bidPct}%` }}
            transition={{ duration: 0.4 }}
          />
          <motion.div
            className="h-full bg-gradient-to-r from-rose-400 to-rose-600"
            animate={{ width: `${100 - bidPct}%` }}
            transition={{ duration: 0.4 }}
          />
        </div>

        {/* Header */}
        <div className="grid grid-cols-3 border-b border-white/6 pb-1 text-[10px] uppercase tracking-widest text-slate-500">
          <span>Price</span>
          <span className="text-right">Size</span>
          <span className="text-right">Depth</span>
        </div>

        {/* Asks (reversed so lowest ask is at bottom) */}
        <div className="space-y-px">
          {[...displayAsks].reverse().map(([price, qty], i) => {
            const pct = (qty / maxQty) * 100;
            return (
              <div
                key={`ask-${i}`}
                className="relative grid grid-cols-3 items-center py-px transition-colors"
              >
                {/* Heatmap background */}
                <div
                  className="absolute inset-y-0 right-0 transition-all duration-300"
                  style={{
                    width: `${pct}%`,
                    background: heatColor(pct, "ask"),
                  }}
                />
                <span className="relative text-rose-400">
                  {price.toFixed(2)}
                </span>
                <span className="relative text-right text-slate-300">
                  {qty.toFixed(4)}
                </span>
                <span className="relative text-right text-slate-500">
                  {pct.toFixed(0)}%
                </span>
              </div>
            );
          })}
        </div>

        {/* Spread / Price */}
        <div className="my-1 flex items-center justify-between border-y border-white/8 py-2">
          <motion.span
            key={lastPrice}
            initial={{ color: "#10b981" }}
            animate={{ color: "#f1f5f9" }}
            transition={{ duration: 0.6 }}
            className="text-sm font-bold text-slate-100"
          >
            {lastPrice !== null ? lastPrice.toFixed(2) : "--"}
          </motion.span>
          <div className="flex items-center gap-2">
            {displayAsks.length > 0 && displayBids.length > 0 && (
              <span className="text-[10px] text-slate-500">
                Spread {(displayAsks[0][0] - displayBids[0][0]).toFixed(2)}
              </span>
            )}
          </div>
        </div>

        {/* Bids */}
        <div className="space-y-px">
          {displayBids.map(([price, qty], i) => {
            const pct = (qty / maxQty) * 100;
            return (
              <div
                key={`bid-${i}`}
                className="relative grid grid-cols-3 items-center py-px transition-colors"
              >
                {/* Heatmap background */}
                <div
                  className="absolute inset-y-0 right-0 transition-all duration-300"
                  style={{
                    width: `${pct}%`,
                    background: heatColor(pct, "bid"),
                  }}
                />
                <span className="relative text-emerald-400">
                  {price.toFixed(2)}
                </span>
                <span className="relative text-right text-slate-300">
                  {qty.toFixed(4)}
                </span>
                <span className="relative text-right text-slate-500">
                  {pct.toFixed(0)}%
                </span>
              </div>
            );
          })}
        </div>

        {/* Volume summary */}
        <div className="mt-2 grid grid-cols-2 gap-2 rounded border border-white/[0.05] bg-slate-900/30 px-2 py-1.5 text-[10px]">
          <div className="text-center">
            <span className="text-slate-500">Bid Vol</span>
            <p className="font-semibold text-emerald-400">
              {bidVolume.toFixed(3)}
            </p>
          </div>
          <div className="text-center">
            <span className="text-slate-500">Ask Vol</span>
            <p className="font-semibold text-rose-400">
              {askVolume.toFixed(3)}
            </p>
          </div>
        </div>
      </div>
    </TerminalCard>
  );
}

export const OrderbookPanel = memo(OrderbookPanelInner);
