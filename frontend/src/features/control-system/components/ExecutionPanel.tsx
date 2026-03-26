"use client";

import { AnimatedNumber } from "@/components/system/animated-number";
import { TerminalCard } from "@/components/ui/terminal-card";
import { controlApi } from "@/services/api/controlApi";
import { useControlSystemStore } from "@/store/controlSystemStore";
import { useMemo, useState } from "react";

export function ExecutionPanel() {
  const symbol = useControlSystemStore((state) => state.symbol);
  const history = useControlSystemStore((state) => state.executions);
  const activeOrders = useControlSystemStore((state) => state.activeExecutions);
  const appendLog = useControlSystemStore((state) => state.appendLog);
  const [sizeUsd, setSizeUsd] = useState(250);
  const [busy, setBusy] = useState(false);

  const slippageStats = useMemo(() => {
    const slippages = history
      .map((order) => {
        if (!Number.isFinite(order.expectedPrice) || !order.expectedPrice)
          return null;
        return (
          ((order.price - order.expectedPrice) / order.expectedPrice) * 10000
        );
      })
      .filter(
        (value): value is number => value !== null && Number.isFinite(value),
      );

    if (slippages.length === 0) {
      return { avg: 0, worst: 0 };
    }

    return {
      avg: slippages.reduce((sum, value) => sum + value, 0) / slippages.length,
      worst: Math.max(...slippages.map((value) => Math.abs(value))),
    };
  }, [history]);

  async function submit(action: "buy" | "sell" | "close") {
    setBusy(true);
    try {
      const response =
        action === "close"
          ? await controlApi.closePosition(symbol)
          : await controlApi.runManual(action, symbol, sizeUsd);
      appendLog(
        `${new Date().toISOString()} EXEC ${action.toUpperCase()} ${JSON.stringify(response)}`,
      );
    } catch (error) {
      appendLog(`${new Date().toISOString()} EXEC ERROR ${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <TerminalCard title="Execution" className="h-full">
      <div className="space-y-3">
        <div className="grid gap-2 sm:grid-cols-3">
          <button
            disabled={busy}
            onClick={() => submit("buy")}
            className="rounded-lg border border-emerald-400/40 bg-emerald-500/10 px-3 py-2 text-xs font-semibold tracking-[0.08em] text-emerald-200 disabled:opacity-50"
          >
            Buy
          </button>
          <button
            disabled={busy}
            onClick={() => submit("sell")}
            className="rounded-lg border border-rose-400/40 bg-rose-500/10 px-3 py-2 text-xs font-semibold tracking-[0.08em] text-rose-200 disabled:opacity-50"
          >
            Sell
          </button>
          <button
            disabled={busy}
            onClick={() => submit("close")}
            className="rounded-lg border border-amber-300/40 bg-amber-500/10 px-3 py-2 text-xs font-semibold tracking-[0.08em] text-amber-200 disabled:opacity-50"
          >
            Close
          </button>
        </div>

        <div className="rounded-xl border border-white/10 bg-slate-900/60 p-3">
          <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-slate-400">
            Order size USD
          </label>
          <input
            type="number"
            min={10}
            value={sizeUsd}
            onChange={(event) => setSizeUsd(Number(event.target.value))}
            className="w-full rounded border border-white/10 bg-slate-950 px-2 py-2 text-sm text-slate-100 outline-none ring-cyan-500/45 transition focus:ring-2"
          />
        </div>

        <div className="grid gap-2 sm:grid-cols-2">
          <div className="rounded-xl border border-white/10 bg-slate-900/60 p-3">
            <p className="text-[11px] uppercase tracking-[0.12em] text-slate-400">
              Avg slippage (bps)
            </p>
            <AnimatedNumber
              value={slippageStats.avg}
              decimals={2}
              className="text-xl text-cyan-200"
            />
          </div>
          <div className="rounded-xl border border-white/10 bg-slate-900/60 p-3">
            <p className="text-[11px] uppercase tracking-[0.12em] text-slate-400">
              Worst slippage (abs bps)
            </p>
            <AnimatedNumber
              value={slippageStats.worst}
              decimals={2}
              className="text-xl text-amber-200"
            />
          </div>
        </div>

        <div className="rounded-xl border border-white/10 bg-slate-900/60 p-2">
          <p className="mb-2 text-[11px] uppercase tracking-[0.12em] text-slate-400">
            Active orders
          </p>
          <div className="max-h-28 space-y-1 overflow-auto">
            {activeOrders.slice(0, 20).map((order) => (
              <div
                key={order.id}
                className="grid grid-cols-[80px_55px_1fr] gap-2 rounded border border-white/8 px-2 py-1 text-[11px]"
              >
                <span className="text-slate-200">{order.symbol}</span>
                <span className="text-cyan-200">{order.side}</span>
                <span className="text-right text-slate-400">
                  {order.status}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-white/10 bg-slate-900/60 p-2">
          <p className="mb-2 text-[11px] uppercase tracking-[0.12em] text-slate-400">
            Venue routing + fills
          </p>
          <div className="max-h-52 space-y-1 overflow-auto">
            {history.slice(0, 50).map((order) => (
              <div
                key={order.id}
                className="grid grid-cols-[75px_52px_1fr_65px] gap-2 rounded border border-white/8 px-2 py-1 text-[11px]"
              >
                <span className="text-slate-200">{order.symbol}</span>
                <span
                  className={
                    order.side.toLowerCase().includes("buy")
                      ? "text-emerald-300"
                      : "text-rose-300"
                  }
                >
                  {order.side}
                </span>
                <span className="truncate text-slate-400">
                  {order.venue} {order.route}
                </span>
                <span className="text-right text-slate-200">
                  {order.price.toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </TerminalCard>
  );
}
