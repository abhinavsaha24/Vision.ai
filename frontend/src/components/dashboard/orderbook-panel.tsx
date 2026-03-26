"use client";

import { memo, useMemo } from "react";
import { TerminalCard } from "@/components/ui/terminal-card";

interface OrderbookPanelProps {
  bids: [number, number][];
  asks: [number, number][];
  lastPrice: number | null;
  imbalance: number | null;
}

const MAX_ROWS = 12;

function OrderbookPanelInner({
  bids,
  asks,
  lastPrice,
  imbalance,
}: OrderbookPanelProps) {
  const { displayBids, displayAsks, maxQty } = useMemo(() => {
    const sortedBids = [...bids].sort((a, b) => b[0] - a[0]).slice(0, MAX_ROWS);
    const sortedAsks = [...asks].sort((a, b) => a[0] - b[0]).slice(0, MAX_ROWS);
    const allQtys = [...sortedBids, ...sortedAsks].map((l) => l[1]);
    const max = Math.max(...allQtys, 1);
    return { displayBids: sortedBids, displayAsks: sortedAsks, maxQty: max };
  }, [bids, asks]);

  const imbalanceColor =
    imbalance === null
      ? "text-slate-400"
      : imbalance > 0.1
        ? "text-emerald-400"
        : imbalance < -0.1
          ? "text-rose-400"
          : "text-slate-300";

  return (
    <TerminalCard
      title="Order Book"
      right={
        <span className={`font-mono text-xs ${imbalanceColor}`}>
          IMB{" "}
          {imbalance !== null
            ? (imbalance > 0 ? "+" : "") + imbalance.toFixed(3)
            : "--"}
        </span>
      }
    >
      <div className="space-y-0.5 text-[11px] font-mono">
        {/* Header */}
        <div className="grid grid-cols-3 text-[10px] uppercase tracking-widest text-slate-500 pb-1 border-b border-white/6">
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
                className="relative grid grid-cols-3 items-center py-px"
              >
                <div
                  className="absolute inset-y-0 right-0 bg-rose-500/8"
                  style={{ width: `${pct}%` }}
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
        <div className="flex items-center justify-between border-y border-white/8 py-1.5 my-1">
          <span className="text-xs font-semibold text-slate-100">
            {lastPrice !== null ? lastPrice.toFixed(2) : "--"}
          </span>
          {displayAsks.length > 0 && displayBids.length > 0 && (
            <span className="text-[10px] text-slate-500">
              Spread {(displayAsks[0][0] - displayBids[0][0]).toFixed(2)}
            </span>
          )}
        </div>

        {/* Bids */}
        <div className="space-y-px">
          {displayBids.map(([price, qty], i) => {
            const pct = (qty / maxQty) * 100;
            return (
              <div
                key={`bid-${i}`}
                className="relative grid grid-cols-3 items-center py-px"
              >
                <div
                  className="absolute inset-y-0 right-0 bg-emerald-500/8"
                  style={{ width: `${pct}%` }}
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
      </div>
    </TerminalCard>
  );
}

export const OrderbookPanel = memo(OrderbookPanelInner);
