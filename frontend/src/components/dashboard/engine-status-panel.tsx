"use client";

import { memo } from "react";
import { TerminalCard } from "@/components/ui/terminal-card";

interface ChannelStatus {
  name: string;
  connected: boolean;
}

interface EngineStatusPanelProps {
  channels: ChannelStatus[];
  reconnectCount: number;
  lastLatencyMs: number | null;
  messagesReceived: number;
  uptime: string;
}

function StatusDot({ active }: { active: boolean }) {
  return (
    <span className="relative flex h-2 w-2">
      {active && (
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
      )}
      <span
        className={`relative inline-flex h-2 w-2 rounded-full ${
          active ? "bg-emerald-400" : "bg-rose-400"
        }`}
      />
    </span>
  );
}

function EngineStatusPanelInner({
  channels,
  reconnectCount,
  lastLatencyMs,
  messagesReceived,
  uptime,
}: EngineStatusPanelProps) {
  const connectedCount = channels.filter((c) => c.connected).length;
  const allConnected = connectedCount === channels.length;

  return (
    <TerminalCard
      title="Engine Status"
      right={
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
            allConnected
              ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
              : "bg-amber-500/15 text-amber-300 border border-amber-500/30"
          }`}
        >
          {allConnected
            ? "ALL LIVE"
            : `${connectedCount}/${channels.length} LIVE`}
        </span>
      }
    >
      {/* Channels grid */}
      <div className="grid grid-cols-2 gap-2 mb-3">
        {channels.map((ch) => (
          <div
            key={ch.name}
            className="flex items-center gap-2 rounded-lg border border-white/6 bg-slate-900/40 px-2.5 py-2"
          >
            <StatusDot active={ch.connected} />
            <span className="text-[11px] uppercase tracking-wider text-slate-300">
              {ch.name}
            </span>
          </div>
        ))}
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 gap-3 text-xs">
        <div className="rounded-lg border border-white/6 bg-slate-900/40 p-2.5">
          <span className="text-[10px] uppercase tracking-widest text-slate-500">
            Latency
          </span>
          <p className="mt-1 font-mono text-sm text-slate-100">
            {lastLatencyMs !== null ? `${lastLatencyMs.toFixed(0)}ms` : "--"}
          </p>
        </div>
        <div className="rounded-lg border border-white/6 bg-slate-900/40 p-2.5">
          <span className="text-[10px] uppercase tracking-widest text-slate-500">
            Reconnects
          </span>
          <p
            className={`mt-1 font-mono text-sm ${reconnectCount > 0 ? "text-amber-300" : "text-slate-100"}`}
          >
            {reconnectCount}
          </p>
        </div>
        <div className="rounded-lg border border-white/6 bg-slate-900/40 p-2.5">
          <span className="text-[10px] uppercase tracking-widest text-slate-500">
            Messages
          </span>
          <p className="mt-1 font-mono text-sm text-cyan-300">
            {messagesReceived.toLocaleString()}
          </p>
        </div>
        <div className="rounded-lg border border-white/6 bg-slate-900/40 p-2.5">
          <span className="text-[10px] uppercase tracking-widest text-slate-500">
            Uptime
          </span>
          <p className="mt-1 font-mono text-sm text-slate-100">
            {uptime || "--"}
          </p>
        </div>
      </div>
    </TerminalCard>
  );
}

export const EngineStatusPanel = memo(EngineStatusPanelInner);
