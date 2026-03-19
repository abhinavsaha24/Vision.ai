"use client";

import { TerminalCard } from "@/components/ui/terminal-card";

export function LiveFeedPanel({ lines }: { lines: string[] }) {
  return (
    <TerminalCard title="Live Feed">
      <div className="h-52 overflow-auto rounded-lg border border-white/10 bg-slate-950/60 p-3 font-mono text-xs text-slate-300">
        {lines.length === 0 ? (
          <p className="text-slate-500">Awaiting market events...</p>
        ) : (
          lines.slice(-120).map((line, index) => (
            <p
              key={`${index}-${line.slice(0, 20)}`}
              className="whitespace-pre-wrap break-words py-0.5"
            >
              {line}
            </p>
          ))
        )}
      </div>
    </TerminalCard>
  );
}
