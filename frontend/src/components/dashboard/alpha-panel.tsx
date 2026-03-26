"use client";

import { useMarketStore } from "@/store/marketStore";
import { TerminalCard } from "@/components/ui/terminal-card";

function metricColor(value: number) {
  if (value >= 0.6) return "text-emerald-300";
  if (value <= 0.4) return "text-rose-300";
  return "text-amber-300";
}

export function AlphaPanel() {
  const signal = useMarketStore((state) => state.signal);

  return (
    <TerminalCard title="Meta Alpha">
      <div className="space-y-4">
        <div>
          <p className="text-xs uppercase tracking-[0.14em] text-slate-500">
            Alpha Score
          </p>
          <p
            className={`text-3xl font-bold ${metricColor(signal?.alpha_score ?? 0.5)}`}
          >
            {((signal?.alpha_score ?? 0.5) * 100).toFixed(1)}%
          </p>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-800">
            <div
              className="h-full rounded-full bg-linear-to-r from-cyan-500 via-sky-500 to-emerald-400"
              style={{
                width: `${Math.max(0, Math.min(100, (signal?.alpha_score ?? 0.5) * 100))}%`,
              }}
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-xs uppercase tracking-[0.14em] text-slate-500">
              Signal
            </p>
            <p className="mt-1 font-semibold text-slate-100">
              {signal?.direction ?? "HOLD"}
            </p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.14em] text-slate-500">
              Confidence
            </p>
            <p className="mt-1 font-semibold text-slate-100">
              {((signal?.confidence ?? 0.5) * 100).toFixed(1)}%
            </p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.14em] text-slate-500">
              Regime
            </p>
            <p className="mt-1 font-semibold text-slate-100">
              {signal?.market_state ?? "UNKNOWN"}
            </p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.14em] text-slate-500">
              Strategy
            </p>
            <p className="mt-1 font-semibold text-slate-100">
              {signal?.strategy ?? "alpha_model"}
            </p>
          </div>
        </div>
      </div>
    </TerminalCard>
  );
}
