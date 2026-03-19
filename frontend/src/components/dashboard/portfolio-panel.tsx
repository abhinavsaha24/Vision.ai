"use client";

import { useMemo } from "react";
import { TerminalCard } from "@/components/ui/terminal-card";
import { usePortfolioStore } from "@/store/portfolioStore";
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export function PortfolioPanel() {
  const portfolio = usePortfolioStore((state) => state.portfolio);
  const metrics = usePortfolioStore((state) => state.metrics);
  const equityHistory = usePortfolioStore((state) => state.equityHistory);

  const positions = useMemo(
    () => Object.entries(portfolio?.positions ?? {}),
    [portfolio?.positions],
  );

  return (
    <TerminalCard title="Portfolio">
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3 text-sm text-slate-200">
          <div>
            <p className="text-xs uppercase tracking-[0.12em] text-slate-500">
              Equity
            </p>
            <p className="mt-1 text-lg font-semibold">
              ${Number(portfolio?.equity ?? 0).toLocaleString()}
            </p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.12em] text-slate-500">
              Cash
            </p>
            <p className="mt-1 text-lg font-semibold">
              ${Number(portfolio?.cash ?? 0).toLocaleString()}
            </p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.12em] text-slate-500">
              Win Rate
            </p>
            <p className="mt-1 font-semibold">
              {((metrics?.win_rate ?? 0) * 100).toFixed(1)}%
            </p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.12em] text-slate-500">
              Sharpe
            </p>
            <p className="mt-1 font-semibold">
              {Number(metrics?.sharpe_ratio ?? 0).toFixed(2)}
            </p>
          </div>
        </div>

        <div className="h-36 rounded-lg border border-white/10 bg-slate-950/60 p-2">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={equityHistory.slice(-80)}>
              <XAxis dataKey="time" hide />
              <YAxis hide domain={["auto", "auto"]} />
              <Tooltip
                labelFormatter={(value) =>
                  new Date(String(value)).toLocaleTimeString()
                }
                formatter={(value) => [
                  `$${Number(value).toLocaleString()}`,
                  "Equity",
                ]}
                contentStyle={{
                  background: "#020617",
                  border: "1px solid rgba(148,163,184,0.3)",
                  borderRadius: "8px",
                }}
              />
              <Line
                type="monotone"
                dataKey="equity"
                stroke="#22d3ee"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="space-y-2">
          <p className="text-xs uppercase tracking-[0.12em] text-slate-500">
            Open Positions
          </p>
          <div className="max-h-36 space-y-1 overflow-auto rounded-lg border border-white/10 bg-slate-950/60 p-2 text-xs">
            {positions.length === 0 ? (
              <p className="text-slate-500">No open positions</p>
            ) : (
              positions.map(([symbol, position]) => (
                <div
                  key={symbol}
                  className="flex items-center justify-between rounded bg-slate-900/70 px-2 py-1"
                >
                  <span className="font-semibold text-slate-200">{symbol}</span>
                  <span className="text-slate-400">
                    {String(
                      (position as { side?: string }).side ?? "-",
                    ).toUpperCase()}
                  </span>
                  <span className="text-slate-300">
                    {Number(
                      (position as { quantity?: number }).quantity ?? 0,
                    ).toFixed(4)}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </TerminalCard>
  );
}
