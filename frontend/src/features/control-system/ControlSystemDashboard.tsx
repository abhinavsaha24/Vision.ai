"use client";

import { motion } from "framer-motion";
import { useControlSystemStreams } from "@/hooks/useControlSystemStreams";
import { useControlSystemStore } from "@/store/controlSystemStore";
import { MarketMicrostructurePanel } from "@/features/control-system/components/MarketMicrostructurePanel";
import { AlphaEnginePanel } from "@/features/control-system/components/AlphaEnginePanel";
import { ExecutionPanel } from "@/features/control-system/components/ExecutionPanel";
import { SystemHealthPanel } from "@/features/control-system/components/SystemHealthPanel";
import { ControlPanel } from "@/features/control-system/components/ControlPanel";
import { TerminalCard } from "@/components/ui/terminal-card";

const WATCHLIST = [
  "BTCUSDT",
  "ETHUSDT",
  "SOLUSDT",
  "BNBUSDT",
  "XRPUSDT",
  "DOGEUSDT",
];

export function ControlSystemDashboard() {
  useControlSystemStreams();

  const symbol = useControlSystemStore((state) => state.symbol);
  const setSymbol = useControlSystemStore((state) => state.setSymbol);
  const logs = useControlSystemStore((state) => state.logs);

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
      className="space-y-4"
    >
      <TerminalCard
        title="Institutional Trading Control System"
        right={
          <span className="rounded-full border border-cyan-300/35 bg-cyan-400/12 px-2 py-1 text-xs text-cyan-100">
            real-time
          </span>
        }
      >
        <div className="grid gap-2 md:grid-cols-6">
          {WATCHLIST.map((asset) => (
            <button
              key={asset}
              onClick={() => setSymbol(asset)}
              className={`rounded-lg border px-2.5 py-2 text-xs font-semibold tracking-[0.08em] transition ${
                symbol === asset
                  ? "border-cyan-300/50 bg-cyan-400/15 text-cyan-100"
                  : "border-white/12 bg-slate-900/70 text-slate-300 hover:border-cyan-300/35"
              }`}
            >
              {asset}
            </button>
          ))}
        </div>
      </TerminalCard>

      <div className="grid gap-4 xl:grid-cols-12">
        <div className="space-y-4 xl:col-span-8">
          <MarketMicrostructurePanel />
          <div className="grid gap-4 lg:grid-cols-2">
            <ExecutionPanel />
            <AlphaEnginePanel />
          </div>
        </div>

        <div className="space-y-4 xl:col-span-4">
          <SystemHealthPanel />
          <ControlPanel />
          <TerminalCard title="Operator Log">
            <div className="max-h-64 space-y-1 overflow-auto rounded-lg border border-white/10 bg-slate-950/55 p-2">
              {logs
                .slice()
                .reverse()
                .map((line, index) => (
                  <p
                    key={`${line}-${index}`}
                    className="border-b border-white/6 py-1 font-mono text-[11px] text-slate-300 last:border-b-0"
                  >
                    {line}
                  </p>
                ))}
            </div>
          </TerminalCard>
        </div>
      </div>
    </motion.div>
  );
}
