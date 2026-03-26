"use client";

import { TerminalCard } from "@/components/ui/terminal-card";
import { controlApi } from "@/services/api/controlApi";
import { useControlSystemStore } from "@/store/controlSystemStore";
import { useState } from "react";

export function ControlPanel() {
  const symbol = useControlSystemStore((state) => state.symbol);
  const strategies = useControlSystemStore((state) => state.strategies);
  const engineState = useControlSystemStore((state) => state.engineState);
  const appendLog = useControlSystemStore((state) => state.appendLog);
  const [initialCash, setInitialCash] = useState(10000);
  const [intervalSeconds, setIntervalSeconds] = useState(10);
  const [riskLimit, setRiskLimit] = useState(0.02);
  const [busyAction, setBusyAction] = useState<string | null>(null);

  async function runAction(action: string, operation: () => Promise<unknown>) {
    setBusyAction(action);
    try {
      const response = await operation();
      appendLog(
        `${new Date().toISOString()} CONTROL ${action} ${JSON.stringify(response)}`,
      );
    } catch (error) {
      appendLog(
        `${new Date().toISOString()} CONTROL ERROR ${action} ${String(error)}`,
      );
    } finally {
      setBusyAction(null);
    }
  }

  const paper =
    (engineState.paper as Record<string, unknown> | undefined) ?? {};

  return (
    <TerminalCard title="Control Panel" className="h-full">
      <div className="space-y-3">
        <div className="grid gap-2 sm:grid-cols-2">
          <button
            disabled={busyAction !== null}
            onClick={() =>
              runAction("ENGINE_START", () =>
                controlApi.startEngine(symbol, initialCash, intervalSeconds),
              )
            }
            className="rounded-lg border border-emerald-400/40 bg-emerald-500/10 px-3 py-2 text-xs font-semibold tracking-[0.08em] text-emerald-200 disabled:opacity-50"
          >
            Start Engine
          </button>
          <button
            disabled={busyAction !== null}
            onClick={() =>
              runAction("ENGINE_STOP", () => controlApi.stopEngine())
            }
            className="rounded-lg border border-rose-400/40 bg-rose-500/10 px-3 py-2 text-xs font-semibold tracking-[0.08em] text-rose-200 disabled:opacity-50"
          >
            Stop Engine
          </button>
        </div>

        <button
          disabled={busyAction !== null}
          onClick={() =>
            runAction("ENABLE_LIVE", () => controlApi.enableLiveTrading())
          }
          className="w-full rounded-lg border border-cyan-400/40 bg-cyan-500/10 px-3 py-2 text-xs font-semibold tracking-[0.08em] text-cyan-100 disabled:opacity-50"
        >
          Enable Live Mode Gate
        </button>

        <div className="grid gap-2 sm:grid-cols-3">
          <label className="rounded border border-white/10 bg-slate-900/65 p-2 text-xs text-slate-300">
            Cash
            <input
              type="number"
              min={1000}
              value={initialCash}
              onChange={(event) => setInitialCash(Number(event.target.value))}
              className="mt-1 w-full rounded border border-white/10 bg-slate-950 px-2 py-1 text-xs"
            />
          </label>
          <label className="rounded border border-white/10 bg-slate-900/65 p-2 text-xs text-slate-300">
            Interval
            <input
              type="number"
              min={1}
              value={intervalSeconds}
              onChange={(event) =>
                setIntervalSeconds(Number(event.target.value))
              }
              className="mt-1 w-full rounded border border-white/10 bg-slate-950 px-2 py-1 text-xs"
            />
          </label>
          <label className="rounded border border-white/10 bg-slate-900/65 p-2 text-xs text-slate-300">
            Risk limit
            <input
              type="number"
              step="0.001"
              min={0.001}
              value={riskLimit}
              onChange={(event) => setRiskLimit(Number(event.target.value))}
              className="mt-1 w-full rounded border border-white/10 bg-slate-950 px-2 py-1 text-xs"
            />
          </label>
        </div>

        <div className="rounded-xl border border-white/10 bg-slate-900/65 p-2">
          <p className="mb-2 text-[11px] uppercase tracking-[0.12em] text-slate-400">
            Strategies
          </p>
          <div className="space-y-1.5">
            {strategies.map((strategy) => {
              const key = String(strategy.key ?? strategy.name ?? "strategy");
              const active = Boolean(strategy.active);
              return (
                <div
                  key={key}
                  className="grid grid-cols-[1fr_70px_70px_65px] items-center gap-2 rounded border border-white/8 px-2 py-1 text-[11px]"
                >
                  <span className="text-slate-200">
                    {String(strategy.name ?? key)}
                  </span>
                  <button
                    disabled={busyAction !== null}
                    onClick={() =>
                      runAction(`STRAT_START_${key}`, () =>
                        controlApi.startStrategy(key),
                      )
                    }
                    className="rounded border border-emerald-400/30 bg-emerald-500/10 py-1 text-emerald-200 disabled:opacity-50"
                  >
                    Start
                  </button>
                  <button
                    disabled={busyAction !== null}
                    onClick={() =>
                      runAction(`STRAT_STOP_${key}`, () =>
                        controlApi.stopStrategy(key),
                      )
                    }
                    className="rounded border border-rose-400/30 bg-rose-500/10 py-1 text-rose-200 disabled:opacity-50"
                  >
                    Stop
                  </button>
                  <span
                    className={active ? "text-emerald-300" : "text-slate-500"}
                  >
                    {active ? "active" : "inactive"}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        <div className="rounded-xl border border-white/10 bg-slate-900/65 p-2 text-xs text-slate-300">
          <p>Mode: {String(paper.status ?? "unknown")}</p>
          <p>Cycles: {String(paper.cycles ?? "--")}</p>
          <p>Risk clamp: {(riskLimit * 100).toFixed(2)}%</p>
        </div>
      </div>
    </TerminalCard>
  );
}
