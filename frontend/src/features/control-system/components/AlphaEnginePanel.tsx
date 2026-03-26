"use client";

import { AnimatedNumber } from "@/components/system/animated-number";
import { SignalFlash } from "@/components/system/signal-flash";
import { TerminalCard } from "@/components/ui/terminal-card";
import { useControlSystemStore } from "@/store/controlSystemStore";

export function AlphaEnginePanel() {
  const signal = useControlSystemStore((state) => state.signal);
  const lifecycle = useControlSystemStore((state) => state.signalLifecycle);
  const metaAlpha = useControlSystemStore((state) => state.metaAlpha);
  const metrics = useControlSystemStore((state) => state.metrics);

  const triggerFlags = [
    {
      name: "Imbalance",
      active: Math.abs(Number(signal.alphaScore)) >= 0.6,
    },
    {
      name: "Sweep",
      active: Math.abs(Number(signal.probability)) >= 0.65,
    },
    {
      name: "Spread shock",
      active: signal.marketState.toLowerCase().includes("volatile"),
    },
  ];

  const scoreColor =
    signal.direction === "BUY"
      ? "text-emerald-200"
      : signal.direction === "SELL"
        ? "text-rose-200"
        : "text-cyan-100";

  return (
    <TerminalCard title="Alpha Engine" className="h-full">
      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-xl border border-white/10 bg-slate-900/65 p-3">
            <p className="text-[11px] uppercase tracking-[0.13em] text-slate-400">
              Edge strength
            </p>
            <AnimatedNumber
              value={signal.alphaScore * 100}
              decimals={1}
              suffix="%"
              className={`text-3xl font-bold ${scoreColor}`}
            />
            <p className="text-xs text-slate-400">
              Signal {signal.direction} | Regime {signal.regime}
            </p>
          </div>
          <div className="rounded-xl border border-white/10 bg-slate-900/65 p-3">
            <p className="text-[11px] uppercase tracking-[0.13em] text-slate-400">
              OOS metrics
            </p>
            <p className="text-sm text-slate-200">
              Win rate {(metrics.winRate * 100).toFixed(1)}%
            </p>
            <p className="text-sm text-slate-200">
              Sharpe {metrics.sharpeRatio.toFixed(2)}
            </p>
            <p className="text-xs text-slate-400">
              Model {String(metaAlpha.signal ?? "unavailable")}
            </p>
          </div>
        </div>

        <div className="rounded-xl border border-white/10 bg-slate-900/65 p-3">
          <p className="mb-2 text-[11px] uppercase tracking-[0.13em] text-slate-400">
            Event triggers
          </p>
          <div className="grid gap-2 sm:grid-cols-3">
            {triggerFlags.map((flag) => (
              <div
                key={flag.name}
                className="flex items-center gap-2 rounded border border-white/10 px-2 py-1.5 text-xs"
              >
                <SignalFlash
                  active={flag.active}
                  color={
                    flag.active
                      ? signal.direction === "SELL"
                        ? "sell"
                        : "buy"
                      : "neutral"
                  }
                />
                <span className="text-slate-200">{flag.name}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-white/10 bg-slate-900/65 p-3">
          <p className="mb-2 text-[11px] uppercase tracking-[0.13em] text-slate-400">
            Signal lifecycle
          </p>
          <div className="max-h-40 space-y-1.5 overflow-auto">
            {lifecycle.slice(0, 40).map((entry) => (
              <div
                key={entry.id}
                className="grid grid-cols-[70px_75px_1fr] gap-2 rounded border border-white/6 px-2 py-1 text-[11px]"
              >
                <span className="text-slate-400">{entry.stage}</span>
                <span
                  className={
                    entry.direction === "BUY"
                      ? "text-emerald-300"
                      : entry.direction === "SELL"
                        ? "text-rose-300"
                        : "text-cyan-200"
                  }
                >
                  {entry.direction}
                </span>
                <span className="text-slate-300">{entry.notes}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </TerminalCard>
  );
}
