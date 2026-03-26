"use client";

import { AnimatedNumber } from "@/components/system/animated-number";
import { VirtualizedLadder } from "@/components/system/virtualized-ladder";
import { TerminalCard } from "@/components/ui/terminal-card";
import { useControlSystemStore } from "@/store/controlSystemStore";
import { motion } from "framer-motion";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export function MarketMicrostructurePanel() {
  const market = useControlSystemStore((state) => state.market);
  const tape = useControlSystemStore((state) => state.tradeTape);

  const spreadSeries = tape.slice(0, 32).map((trade, index) => ({
    idx: index,
    spread: market.spreadBps,
    price: trade.price,
  }));

  return (
    <TerminalCard
      title="Market Microstructure"
      right={
        <div className="flex items-center gap-2 text-xs">
          <span className="rounded-full border border-cyan-400/35 bg-cyan-400/12 px-2 py-1 text-cyan-100">
            {market.symbol}
          </span>
          <span
            className={market.stale ? "text-amber-300" : "text-emerald-300"}
          >
            {market.stale ? "stale" : "live"}
          </span>
        </div>
      }
      className="h-full"
    >
      <div className="grid gap-4 xl:grid-cols-12">
        <div className="space-y-3 xl:col-span-3">
          <div className="rounded-xl border border-white/10 bg-slate-900/65 p-3">
            <p className="text-[11px] uppercase tracking-[0.12em] text-slate-400">
              Last
            </p>
            <AnimatedNumber
              className="text-2xl font-semibold text-slate-100"
              value={market.lastPrice}
              decimals={2}
            />
          </div>
          <div className="rounded-xl border border-white/10 bg-slate-900/65 p-3">
            <p className="text-[11px] uppercase tracking-[0.12em] text-slate-400">
              Spread (bps)
            </p>
            <AnimatedNumber
              className="text-xl font-semibold text-cyan-200"
              value={market.spreadBps}
              decimals={3}
            />
          </div>
          <div className="rounded-xl border border-white/10 bg-slate-900/65 p-3">
            <p className="text-[11px] uppercase tracking-[0.12em] text-slate-400">
              Imbalance
            </p>
            <AnimatedNumber
              className="text-xl font-semibold text-amber-100"
              value={market.imbalance}
              decimals={3}
            />
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-800">
              <motion.div
                className="h-full rounded-full bg-linear-to-r from-rose-400 via-slate-700 to-emerald-400"
                animate={{ width: `${((market.imbalance + 1) / 2) * 100}%` }}
                transition={{ duration: 0.3 }}
              />
            </div>
          </div>
        </div>

        <div className="xl:col-span-5 grid gap-3 md:grid-cols-2">
          <div>
            <p className="mb-2 text-[11px] uppercase tracking-[0.12em] text-emerald-300">
              Bid ladder
            </p>
            <VirtualizedLadder rows={market.bids} side="bids" />
          </div>
          <div>
            <p className="mb-2 text-[11px] uppercase tracking-[0.12em] text-rose-300">
              Ask ladder
            </p>
            <VirtualizedLadder rows={market.asks} side="asks" />
          </div>
        </div>

        <div className="space-y-3 xl:col-span-4">
          <div className="h-36 min-h-35 rounded-xl border border-white/10 bg-slate-900/70 p-2">
            <p className="mb-1 text-[11px] uppercase tracking-[0.12em] text-slate-400">
              Spread pulse
            </p>
            <ResponsiveContainer
              width="100%"
              height={120}
              minWidth={220}
              minHeight={100}
            >
              <AreaChart data={spreadSeries}>
                <defs>
                  <linearGradient
                    id="spreadGradient"
                    x1="0"
                    y1="0"
                    x2="0"
                    y2="1"
                  >
                    <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.7} />
                    <stop offset="95%" stopColor="#38bdf8" stopOpacity={0.05} />
                  </linearGradient>
                </defs>
                <XAxis hide dataKey="idx" />
                <YAxis hide domain={["auto", "auto"]} />
                <Tooltip
                  formatter={(value) => `${Number(value ?? 0).toFixed(3)} bps`}
                  labelFormatter={() => "Spread"}
                  contentStyle={{
                    background: "#020617",
                    border: "1px solid #334155",
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="spread"
                  stroke="#38bdf8"
                  fill="url(#spreadGradient)"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div className="h-72 overflow-auto rounded-xl border border-white/10 bg-slate-900/70 p-2">
            <p className="mb-2 text-[11px] uppercase tracking-[0.12em] text-slate-400">
              Trade tape
            </p>
            <div className="space-y-1.5">
              {tape.slice(0, 80).map((trade, index) => (
                <motion.div
                  key={`${trade.id}-${trade.ts}-${index}`}
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.15 }}
                  className="grid grid-cols-3 rounded border border-white/5 px-2 py-1 text-[11px]"
                >
                  <span
                    className={
                      trade.side === "buy"
                        ? "text-emerald-300"
                        : trade.side === "sell"
                          ? "text-rose-300"
                          : "text-slate-300"
                    }
                  >
                    {trade.side.toUpperCase()}
                  </span>
                  <span className="text-right font-mono text-slate-200">
                    {trade.price.toFixed(2)}
                  </span>
                  <span className="text-right font-mono text-slate-400">
                    {trade.size.toFixed(4)}
                  </span>
                </motion.div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </TerminalCard>
  );
}
