"use client";

import { AnimatedNumber } from "@/components/system/animated-number";
import { TerminalCard } from "@/components/ui/terminal-card";
import { useControlSystemStore } from "@/store/controlSystemStore";

export function SystemHealthPanel() {
  const health = useControlSystemStore((state) => state.health);
  const readinessScore = useControlSystemStore(
    (state) => state.systemReadinessScore,
  );
  const riskState = useControlSystemStore((state) => state.riskState);

  const statuses = Object.values(health.channelStatus);

  return (
    <TerminalCard title="System Health" className="h-full">
      <div className="space-y-3">
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="rounded-xl border border-white/10 bg-slate-900/65 p-3">
            <p className="text-[11px] uppercase tracking-[0.12em] text-slate-400">
              Readiness score
            </p>
            <AnimatedNumber
              value={readinessScore}
              decimals={1}
              className="text-2xl text-cyan-200"
            />
          </div>
          <div className="rounded-xl border border-white/10 bg-slate-900/65 p-3">
            <p className="text-[11px] uppercase tracking-[0.12em] text-slate-400">
              Risk level
            </p>
            <p className="text-xl font-semibold text-amber-200">
              {String(riskState.risk_level ?? "unknown")}
            </p>
          </div>
        </div>

        <div className="grid gap-2 sm:grid-cols-3">
          <div className="rounded-lg border border-white/10 bg-slate-900/65 p-2">
            <p className="text-[10px] uppercase tracking-[0.12em] text-slate-400">
              Latency
            </p>
            <AnimatedNumber
              value={health.avgLatencyMs}
              decimals={0}
              suffix=" ms"
              className="text-lg text-slate-100"
            />
          </div>
          <div className="rounded-lg border border-white/10 bg-slate-900/65 p-2">
            <p className="text-[10px] uppercase tracking-[0.12em] text-slate-400">
              Reconnects
            </p>
            <AnimatedNumber
              value={health.reconnectCount}
              decimals={0}
              className="text-lg text-slate-100"
            />
          </div>
          <div className="rounded-lg border border-white/10 bg-slate-900/65 p-2">
            <p className="text-[10px] uppercase tracking-[0.12em] text-slate-400">
              Throughput
            </p>
            <AnimatedNumber
              value={health.throughputPerSecond}
              decimals={0}
              suffix=" msg/s"
              className="text-lg text-slate-100"
            />
          </div>
        </div>

        <div className="rounded-xl border border-white/10 bg-slate-900/65 p-2">
          <p className="mb-2 text-[11px] uppercase tracking-[0.12em] text-slate-400">
            WebSocket channels
          </p>
          <div className="space-y-1.5">
            {statuses.map((status) => (
              <div
                key={status.channel}
                className="grid grid-cols-[80px_70px_1fr_80px] gap-2 rounded border border-white/8 px-2 py-1 text-[11px]"
              >
                <span className="text-slate-200">{status.channel}</span>
                <span
                  className={
                    status.connected ? "text-emerald-300" : "text-rose-300"
                  }
                >
                  {status.connected ? "online" : "offline"}
                </span>
                <span className="text-slate-400">
                  gaps {status.seqGapCount}
                </span>
                <span className="text-right text-slate-300">
                  {status.throughputPerSecond} /s
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </TerminalCard>
  );
}
