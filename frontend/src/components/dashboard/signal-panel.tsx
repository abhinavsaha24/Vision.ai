"use client";

import { memo } from "react";
import { motion } from "framer-motion";
import { TerminalCard } from "@/components/ui/terminal-card";

export interface SignalEvent {
  timestamp: string;
  direction: "BUY" | "SELL" | "HOLD";
  confidence: number;
  probability: number;
  alpha_score: number;
  regime: string;
  market_state?: string;
  strategy: string;
}

interface SignalPanelProps {
  signals: SignalEvent[];
  currentSignal: SignalEvent | null;
}

function directionColor(dir: string) {
  if (dir === "BUY") return "text-emerald-400";
  if (dir === "SELL") return "text-rose-400";
  return "text-slate-100";
}

function directionBg(dir: string) {
  if (dir === "BUY") return "bg-emerald-500/15 border-emerald-500/30";
  if (dir === "SELL") return "bg-rose-500/15 border-rose-500/30";
  return "bg-slate-200/10 border-slate-300/30";
}

function confidenceBar(value: number) {
  const pct = Math.min(Math.max(value * 100, 0), 100);
  const color =
    pct >= 70 ? "bg-emerald-500" : pct >= 40 ? "bg-amber-500" : "bg-rose-500";
  return { pct, color };
}

function SignalPanelInner({ signals, currentSignal }: SignalPanelProps) {
  const regimeLabel =
    currentSignal?.regime || currentSignal?.market_state || "INFERENCE";

  const formatTime = (ts: string) => {
    try {
      return new Date(ts).toLocaleTimeString("en-US", { hour12: false });
    } catch {
      return ts;
    }
  };

  return (
    <TerminalCard
      title="Signal Intelligence"
      right={
        currentSignal && (
          <motion.span
            key={currentSignal.direction}
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className={`rounded-md border px-2 py-0.5 text-xs font-bold ${directionBg(currentSignal.direction)} ${directionColor(currentSignal.direction)}`}
          >
            {currentSignal.direction}
          </motion.span>
        )
      }
    >
      {/* Current Signal Card */}
      {currentSignal && (
        <div className="mb-3 rounded-lg border border-white/8 bg-slate-900/50 p-3">
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div>
              <span className="text-[10px] uppercase tracking-widest text-slate-500">
                Confidence
              </span>
              <div className="mt-1 flex items-center gap-2">
                <div className="h-1.5 flex-1 rounded-full bg-slate-800 overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${confidenceBar(currentSignal.confidence).color}`}
                    style={{
                      width: `${confidenceBar(currentSignal.confidence).pct}%`,
                    }}
                  />
                </div>
                <span className="font-mono text-slate-200">
                  {(currentSignal.confidence * 100).toFixed(1)}%
                </span>
              </div>
            </div>
            <div>
              <span className="text-[10px] uppercase tracking-widest text-slate-500">
                Alpha
              </span>
              <p className="mt-1 font-mono text-sm text-cyan-300">
                {currentSignal.alpha_score?.toFixed(4) ?? "--"}
              </p>
            </div>
            <div>
              <span className="text-[10px] uppercase tracking-widest text-slate-500">
                Regime
              </span>
              <p className="mt-1 text-slate-200">{regimeLabel}</p>
            </div>
            <div>
              <span className="text-[10px] uppercase tracking-widest text-slate-500">
                Strategy
              </span>
              <p className="mt-1 text-slate-200">
                {currentSignal.strategy || "--"}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Signal History */}
      <div className="max-h-48 overflow-auto space-y-0">
        <div className="sticky top-0 z-10 grid grid-cols-4 bg-slate-950/90 pb-1 text-[10px] uppercase tracking-widest text-slate-500 border-b border-white/6">
          <span>Time</span>
          <span>Direction</span>
          <span className="text-right">Conf.</span>
          <span className="text-right">Alpha</span>
        </div>

        {signals.length === 0 && (
          <p className="py-4 text-center text-xs text-slate-600">
            No signals detected yet
          </p>
        )}

        {[...signals]
          .reverse()
          .slice(0, 20)
          .map((sig, i) => (
            <div
              key={`sig-${i}`}
              className="grid grid-cols-4 items-center py-0.75 text-[11px] font-mono border-b border-white/3"
            >
              <span className="text-slate-500">
                {formatTime(sig.timestamp)}
              </span>
              <span
                className={`${directionColor(sig.direction)} ${sig.direction === "HOLD" ? "font-extrabold tracking-wide" : "font-semibold"}`}
              >
                {sig.direction}
              </span>
              <span className="text-right text-slate-300">
                {(sig.confidence * 100).toFixed(0)}%
              </span>
              <span className="text-right text-cyan-400">
                {sig.alpha_score?.toFixed(3) ?? "--"}
              </span>
            </div>
          ))}
      </div>
    </TerminalCard>
  );
}

export const SignalPanel = memo(SignalPanelInner);
