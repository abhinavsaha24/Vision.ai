"use client";

import axios from "axios";
import { useEffect, useMemo, useState } from "react";
import { apiService } from "@/services/api";
import { useMarketStore } from "@/store/marketStore";
import { TerminalCard } from "@/components/ui/terminal-card";

interface TradingPanelProps {
  onExecutionLog: (line: string) => void;
}

type MeResponse = { role?: string };
type PaperStatusResponse = { running?: boolean; status?: string };
type LiveReadinessResponse = {
  all_ready?: boolean;
  overall_score?: number;
  blocked_reasons?: string[];
};

export function TradingPanel({ onExecutionLog }: TradingPanelProps) {
  const symbol = useMarketStore((state) => state.symbol);
  const signal = useMarketStore((state) => state.signal);
  const [sizeUsd, setSizeUsd] = useState(250);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  const [paperRunning, setPaperRunning] = useState<boolean | null>(null);
  const [startingPaper, setStartingPaper] = useState(false);
  const [stoppingPaper, setStoppingPaper] = useState(false);
  const [killing, setKilling] = useState(false);
  const [resettingKill, setResettingKill] = useState(false);
  const [enablingLive, setEnablingLive] = useState(false);
  const [liveReady, setLiveReady] = useState<boolean | null>(null);
  const [liveReadinessScore, setLiveReadinessScore] = useState<number | null>(
    null,
  );
  const [liveBlockedReasons, setLiveBlockedReasons] = useState<string[]>([]);

  const executionBias = useMemo(() => {
    if (!signal) return "NEUTRAL";
    if (signal.alpha_score >= 0.6 && signal.direction === "BUY")
      return "LONG BIAS";
    if (signal.alpha_score <= 0.4 && signal.direction === "SELL")
      return "SHORT BIAS";
    return "NEUTRAL";
  }, [signal]);

  useEffect(() => {
    let active = true;

    const refreshExecutionGuard = async () => {
      try {
        const [me, paperStatus, liveReadiness] = await Promise.all([
          apiService.getMe(),
          apiService.getPaperStatus(),
          apiService.getLiveTradingReadiness(),
        ]);

        if (!active) return;

        const meData = me as MeResponse;
        const statusData = paperStatus as PaperStatusResponse;
        const readinessData = liveReadiness as LiveReadinessResponse;
        const role = String(meData?.role ?? "").toLowerCase();
        const running =
          statusData?.running === true || statusData?.status === "running";

        setIsAdmin(role === "admin");
        setPaperRunning(running);
        setLiveReady(Boolean(readinessData?.all_ready));
        setLiveReadinessScore(
          typeof readinessData?.overall_score === "number"
            ? readinessData.overall_score
            : null,
        );
        setLiveBlockedReasons(
          Array.isArray(readinessData?.blocked_reasons)
            ? readinessData.blocked_reasons
            : [],
        );
      } catch {
        if (!active) return;
        setIsAdmin(false);
        setPaperRunning(false);
        setLiveReady(false);
        setLiveReadinessScore(null);
        setLiveBlockedReasons(["readiness_refresh_unavailable"]);
      }
    };

    void refreshExecutionGuard();
    const intervalId = window.setInterval(refreshExecutionGuard, 15000);

    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, []);

  const executionGuardReason = useMemo(() => {
    if (isAdmin === null || paperRunning === null) {
      return "Checking execution readiness...";
    }
    if (!isAdmin) {
      return "Manual execution requires an admin account.";
    }
    if (!paperRunning) {
      return "Paper trading is not running. Start it before executing orders.";
    }
    return null;
  }, [isAdmin, paperRunning]);

  const paperStatusChip = useMemo(() => {
    if (startingPaper) {
      return {
        label: "PAPER: STARTING",
        className: "border-cyan-400/40 bg-cyan-500/10 text-cyan-200",
      };
    }
    if (stoppingPaper) {
      return {
        label: "PAPER: STOPPING",
        className: "border-amber-400/40 bg-amber-500/10 text-amber-200",
      };
    }
    if (paperRunning === null) {
      return {
        label: "PAPER: CHECKING",
        className: "border-slate-400/40 bg-slate-500/10 text-slate-200",
      };
    }
    if (paperRunning) {
      return {
        label: "PAPER: RUNNING",
        className: "border-emerald-400/40 bg-emerald-500/10 text-emerald-200",
      };
    }
    return {
      label: "PAPER: STOPPED",
      className: "border-rose-400/40 bg-rose-500/10 text-rose-200",
    };
  }, [paperRunning, startingPaper, stoppingPaper]);

  const liveStatusChip = useMemo(() => {
    if (enablingLive) {
      return {
        label: "LIVE: ENABLING",
        className: "border-cyan-400/40 bg-cyan-500/10 text-cyan-200",
      };
    }
    if (liveReady === null) {
      return {
        label: "LIVE: CHECKING",
        className: "border-slate-400/40 bg-slate-500/10 text-slate-200",
      };
    }
    if (liveReady) {
      return {
        label: "LIVE: READY",
        className: "border-emerald-400/40 bg-emerald-500/10 text-emerald-200",
      };
    }
    return {
      label: "LIVE: BLOCKED",
      className: "border-rose-400/40 bg-rose-500/10 text-rose-200",
    };
  }, [enablingLive, liveReady]);

  const canExecute = !submitting && !executionGuardReason;

  async function execute(action: "buy" | "sell" | "close") {
    if (executionGuardReason) {
      setError(executionGuardReason);
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const idempotencyKey = apiService.generateIdempotencyKey(action);
      let response: unknown;
      if (action === "buy")
        response = await apiService.manualBuy(symbol, sizeUsd, idempotencyKey);
      if (action === "sell")
        response = await apiService.manualSell(symbol, sizeUsd, idempotencyKey);
      if (action === "close") {
        response = await apiService.closePosition(symbol, idempotencyKey);
      }
      onExecutionLog(
        `${new Date().toISOString()}  ${action.toUpperCase()} ${symbol} [${idempotencyKey}] ${JSON.stringify(response)}`,
      );
    } catch (err) {
      let message = err instanceof Error ? err.message : "execution failed";
      if (axios.isAxiosError(err)) {
        const detail = err.response?.data as
          | { detail?: string; error?: string; message?: string }
          | undefined;
        message =
          detail?.detail || detail?.message || detail?.error || err.message;
      }
      setError(message);
      onExecutionLog(`${new Date().toISOString()}  ERROR ${message}`);
    } finally {
      setSubmitting(false);
    }
  }

  async function triggerEmergencyKill() {
    setKilling(true);
    setError(null);
    try {
      const response = await apiService.emergencyKill(
        "manual_terminal_override",
      );
      onExecutionLog(
        `${new Date().toISOString()}  EMERGENCY_KILL ${symbol}  ${JSON.stringify(response)}`,
      );
    } catch (err) {
      let message =
        err instanceof Error ? err.message : "failed to activate kill switch";
      if (axios.isAxiosError(err)) {
        const detail = err.response?.data as
          | { detail?: string; error?: string; message?: string }
          | undefined;
        message =
          detail?.detail || detail?.message || detail?.error || err.message;
      }
      setError(message);
      onExecutionLog(`${new Date().toISOString()}  ERROR ${message}`);
    } finally {
      setKilling(false);
    }
  }

  async function triggerEmergencyReset() {
    setResettingKill(true);
    setError(null);
    try {
      const response = await apiService.emergencyKillReset();
      onExecutionLog(
        `${new Date().toISOString()}  EMERGENCY_RESET ${symbol}  ${JSON.stringify(response)}`,
      );
    } catch (err) {
      let message =
        err instanceof Error ? err.message : "failed to reset kill switch";
      if (axios.isAxiosError(err)) {
        const detail = err.response?.data as
          | { detail?: string; error?: string; message?: string }
          | undefined;
        message =
          detail?.detail || detail?.message || detail?.error || err.message;
      }
      setError(message);
      onExecutionLog(`${new Date().toISOString()}  ERROR ${message}`);
    } finally {
      setResettingKill(false);
    }
  }

  async function startPaperTrading() {
    setStartingPaper(true);
    setError(null);
    try {
      const response = await apiService.startPaperTrading(symbol);
      setPaperRunning(true);
      onExecutionLog(
        `${new Date().toISOString()}  PAPER_START ${symbol}  ${JSON.stringify(response)}`,
      );
    } catch (err) {
      let message =
        err instanceof Error ? err.message : "failed to start paper trading";
      if (axios.isAxiosError(err)) {
        const detail = err.response?.data as
          | { detail?: string; error?: string; message?: string }
          | undefined;
        message =
          detail?.detail || detail?.message || detail?.error || err.message;
      }
      setError(message);
      onExecutionLog(`${new Date().toISOString()}  ERROR ${message}`);
    } finally {
      setStartingPaper(false);
    }
  }

  async function stopPaperTrading() {
    setStoppingPaper(true);
    setError(null);
    try {
      const response = await apiService.stopPaperTrading();
      setPaperRunning(false);
      onExecutionLog(
        `${new Date().toISOString()}  PAPER_STOP ${symbol}  ${JSON.stringify(response)}`,
      );
    } catch (err) {
      let message =
        err instanceof Error ? err.message : "failed to stop paper trading";
      if (axios.isAxiosError(err)) {
        const detail = err.response?.data as
          | { detail?: string; error?: string; message?: string }
          | undefined;
        message =
          detail?.detail || detail?.message || detail?.error || err.message;
      }
      setError(message);
      onExecutionLog(`${new Date().toISOString()}  ERROR ${message}`);
    } finally {
      setStoppingPaper(false);
    }
  }

  async function enableLiveTrading() {
    setEnablingLive(true);
    setError(null);
    try {
      const response = await apiService.enableLiveTrading();
      setLiveReady(true);
      onExecutionLog(
        `${new Date().toISOString()}  LIVE_ENABLE ${symbol}  ${JSON.stringify(response)}`,
      );
    } catch (err) {
      let message =
        err instanceof Error ? err.message : "failed to enable live trading";
      if (axios.isAxiosError(err)) {
        const detail = err.response?.data as
          | { detail?: string; error?: string; message?: string }
          | undefined;
        message =
          detail?.detail || detail?.message || detail?.error || err.message;
      }
      setError(message);
      onExecutionLog(`${new Date().toISOString()}  ERROR ${message}`);
    } finally {
      setEnablingLive(false);
    }
  }

  const paperControl = startingPaper
    ? {
        label: "Starting Paper Trading...",
        className:
          "border-cyan-500/40 bg-cyan-500/10 text-cyan-200 hover:bg-cyan-500/20",
        onClick: startPaperTrading,
      }
    : stoppingPaper
      ? {
          label: "Stopping Paper Trading...",
          className:
            "border-amber-500/40 bg-amber-500/10 text-amber-200 hover:bg-amber-500/20",
          onClick: stopPaperTrading,
        }
      : paperRunning
        ? {
            label: "Stop Paper Trading",
            className:
              "border-rose-500/40 bg-rose-500/10 text-rose-200 hover:bg-rose-500/20",
            onClick: stopPaperTrading,
          }
        : {
            label: "Start Paper Trading",
            className:
              "border-cyan-500/40 bg-cyan-500/10 text-cyan-200 hover:bg-cyan-500/20",
            onClick: startPaperTrading,
          };

  return (
    <TerminalCard
      title="Execution"
      right={
        <div className="flex items-center gap-2">
          <span className="text-xs text-cyan-300">{executionBias}</span>
          <span
            className={`rounded border px-2 py-0.5 text-[10px] font-semibold tracking-[0.08em] ${paperStatusChip.className}`}
          >
            {paperStatusChip.label}
          </span>
          <span
            className={`rounded border px-2 py-0.5 text-[10px] font-semibold tracking-[0.08em] ${liveStatusChip.className}`}
          >
            {liveStatusChip.label}
          </span>
        </div>
      }
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3 text-xs text-slate-300">
          <div>
            <p className="mb-1 text-slate-500">Symbol</p>
            <p className="font-semibold">{symbol}</p>
          </div>
          <div>
            <p className="mb-1 text-slate-500">Alpha</p>
            <p className="font-semibold">
              {((signal?.alpha_score ?? 0.5) * 100).toFixed(1)}%
            </p>
          </div>
        </div>

        <div>
          <label className="mb-2 block text-xs uppercase tracking-[0.15em] text-slate-400">
            Position Size USD
          </label>
          <input
            type="number"
            min={10}
            value={sizeUsd}
            onChange={(event) => setSizeUsd(Number(event.target.value))}
            className="w-full rounded-lg border border-white/10 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none ring-cyan-500/50 transition focus:ring-2"
          />
        </div>

        <div className="grid grid-cols-3 gap-2">
          <button
            disabled={!canExecute}
            onClick={() => execute("buy")}
            title={executionGuardReason ?? undefined}
            className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm font-semibold text-emerald-300 transition hover:bg-emerald-500/20 disabled:opacity-50"
          >
            Buy
          </button>
          <button
            disabled={!canExecute}
            onClick={() => execute("sell")}
            title={executionGuardReason ?? undefined}
            className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm font-semibold text-rose-300 transition hover:bg-rose-500/20 disabled:opacity-50"
          >
            Sell
          </button>
          <button
            disabled={!canExecute}
            onClick={() => execute("close")}
            title={executionGuardReason ?? undefined}
            className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm font-semibold text-amber-200 transition hover:bg-amber-500/20 disabled:opacity-50"
          >
            Close
          </button>
        </div>

        {executionGuardReason ? (
          <p className="text-xs text-amber-300">{executionGuardReason}</p>
        ) : null}
        {isAdmin ? (
          <>
            <button
              disabled={
                stoppingPaper ||
                startingPaper ||
                submitting ||
                killing ||
                resettingKill
              }
              onClick={paperControl.onClick}
              className={`w-full rounded-lg border px-3 py-2 text-sm font-semibold transition disabled:opacity-50 ${paperControl.className}`}
            >
              {paperControl.label}
            </button>
            <button
              disabled={
                !liveReady ||
                enablingLive ||
                submitting ||
                killing ||
                resettingKill
              }
              onClick={enableLiveTrading}
              title={
                !liveReady && liveBlockedReasons.length > 0
                  ? liveBlockedReasons.join(" | ")
                  : undefined
              }
              className="w-full rounded-lg border border-violet-500/40 bg-violet-500/10 px-3 py-2 text-sm font-semibold text-violet-200 transition hover:bg-violet-500/20 disabled:opacity-50"
            >
              {enablingLive
                ? "Enabling Live Trading..."
                : "Enable Live Trading"}
            </button>
            {liveReadinessScore !== null ? (
              <p className="text-xs text-slate-400">
                Live readiness score: {liveReadinessScore.toFixed(1)}
              </p>
            ) : null}
            {!liveReady && liveBlockedReasons.length > 0 ? (
              <p className="text-xs text-amber-300">
                Live blockers: {liveBlockedReasons.join("; ")}
              </p>
            ) : null}
            <div className="grid grid-cols-2 gap-2">
              <button
                disabled={submitting || killing || resettingKill}
                onClick={triggerEmergencyKill}
                className="rounded-lg border border-rose-500/50 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 transition hover:bg-rose-500/20 disabled:opacity-50"
              >
                {killing ? "KILLING..." : "Emergency Kill"}
              </button>
              <button
                disabled={submitting || killing || resettingKill}
                onClick={triggerEmergencyReset}
                className="rounded-lg border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-xs font-semibold text-amber-200 transition hover:bg-amber-500/20 disabled:opacity-50"
              >
                {resettingKill ? "RESETTING..." : "Reset Kill"}
              </button>
            </div>
          </>
        ) : null}
        {error ? <p className="text-xs text-rose-300">{error}</p> : null}
      </div>
    </TerminalCard>
  );
}
