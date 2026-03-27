"use client";

import { useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { apiService } from "@/services/api";
import { TerminalCard } from "@/components/ui/terminal-card";

interface RiskState {
  kill_switch_active: boolean;
  max_drawdown: number;
  current_drawdown: number;
  current_exposure: number;
  max_exposure: number;
  var_breach: boolean;
  risk_level: "NORMAL" | "ELEVATED" | "CRITICAL";
  daily_loss_pct: number;
  open_positions: number;
  max_open_trades: number;
}

const DEFAULT_RISK: RiskState = {
  kill_switch_active: false,
  max_drawdown: 0.2,
  current_drawdown: 0,
  current_exposure: 0,
  max_exposure: 1.0,
  var_breach: false,
  risk_level: "NORMAL",
  daily_loss_pct: 0,
  open_positions: 0,
  max_open_trades: 5,
};

function BarMeter({
  value,
  max,
  label,
  color = "cyan",
  showPct = true,
}: {
  value: number;
  max: number;
  label: string;
  color?: "cyan" | "amber" | "rose" | "emerald";
  showPct?: boolean;
}) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  const colorMap = {
    cyan: {
      bg: "bg-cyan-500/20",
      fill: "bg-gradient-to-r from-cyan-500 to-cyan-400",
      text: "text-cyan-300",
    },
    amber: {
      bg: "bg-amber-500/20",
      fill: "bg-gradient-to-r from-amber-500 to-amber-400",
      text: "text-amber-300",
    },
    rose: {
      bg: "bg-rose-500/20",
      fill: "bg-gradient-to-r from-rose-500 to-rose-400",
      text: "text-rose-300",
    },
    emerald: {
      bg: "bg-emerald-500/20",
      fill: "bg-gradient-to-r from-emerald-500 to-emerald-400",
      text: "text-emerald-300",
    },
  };
  const c = colorMap[color];

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-widest text-slate-500">
          {label}
        </span>
        <span className={`font-mono text-xs font-semibold ${c.text}`}>
          {showPct ? `${pct.toFixed(1)}%` : value.toFixed(2)}
        </span>
      </div>
      <div className={`h-1.5 w-full overflow-hidden rounded-full ${c.bg}`}>
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
          className={`h-full rounded-full ${c.fill}`}
        />
      </div>
    </div>
  );
}

function DrawdownSparkline({ values }: { values: number[] }) {
  if (values.length < 2) {
    return (
      <div className="flex h-10 items-center justify-center text-[10px] text-slate-600">
        Awaiting drawdown history...
      </div>
    );
  }

  const max = Math.max(...values, 0.001);
  const w = 200;
  const h = 36;
  const stepX = w / (values.length - 1);
  const points = values
    .map((v, i) => `${i * stepX},${h - (v / max) * h}`)
    .join(" ");
  const fill = `${points} ${w},${h} 0,${h}`;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full" preserveAspectRatio="none">
      <defs>
        <linearGradient id="dd-gradient" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgba(244,63,94,0.4)" />
          <stop offset="100%" stopColor="rgba(244,63,94,0)" />
        </linearGradient>
      </defs>
      <polygon points={fill} fill="url(#dd-gradient)" />
      <polyline
        points={points}
        fill="none"
        stroke="#f43f5e"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function RiskPanel() {
  const [risk, setRisk] = useState<RiskState>(DEFAULT_RISK);
  const [drawdownHistory, setDrawdownHistory] = useState<number[]>([]);

  useEffect(() => {
    let active = true;

    const fetchRisk = async () => {
      try {
        const data = (await apiService.getHealth()) as Record<string, unknown>;
        if (!active) return;

        const killSwitch = Boolean(
          (data as Record<string, unknown>)?.kill_switch ??
            (data as Record<string, unknown>)?.kill_switch_active ??
            false,
        );

        let dd = 0;
        let dailyLoss = 0;
        let exposure = 0;

        try {
          const portfolio = (await apiService.getPortfolioPerformance()) as Record<
            string,
            unknown
          >;
          dd = Number(portfolio?.max_drawdown ?? 0);
          dailyLoss = Number(portfolio?.daily_pnl_pct ?? 0);
          exposure = Number(portfolio?.positions_value ?? 0) / Math.max(Number(portfolio?.current_equity ?? 1), 1);
        } catch {
          // Portfolio may not be available
        }

        const level: RiskState["risk_level"] =
          killSwitch || dd > 0.15
            ? "CRITICAL"
            : dd > 0.08
              ? "ELEVATED"
              : "NORMAL";

        setRisk({
          kill_switch_active: killSwitch,
          max_drawdown: 0.2,
          current_drawdown: Math.abs(dd),
          current_exposure: Math.abs(exposure),
          max_exposure: 1.0,
          var_breach: dd > 0.15,
          risk_level: level,
          daily_loss_pct: Math.abs(dailyLoss),
          open_positions: 0,
          max_open_trades: 5,
        });

        setDrawdownHistory((prev) =>
          [...prev, Math.abs(dd)].slice(-60),
        );
      } catch {
        // Silent failure — don't crash the panel
      }
    };

    void fetchRisk();
    const interval = window.setInterval(fetchRisk, 10000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  const levelConfig = useMemo(() => {
    switch (risk.risk_level) {
      case "CRITICAL":
        return {
          color: "text-rose-400",
          bg: "bg-rose-500/15 border-rose-500/30",
          icon: "🔴",
        };
      case "ELEVATED":
        return {
          color: "text-amber-400",
          bg: "bg-amber-500/15 border-amber-500/30",
          icon: "🟡",
        };
      default:
        return {
          color: "text-emerald-400",
          bg: "bg-emerald-500/15 border-emerald-500/30",
          icon: "🟢",
        };
    }
  }, [risk.risk_level]);

  return (
    <TerminalCard
      title="Risk Monitor"
      right={
        <div className="flex items-center gap-2">
          <span
            className={`rounded-full border px-2 py-0.5 text-[10px] font-bold tracking-widest ${levelConfig.bg} ${levelConfig.color}`}
          >
            {levelConfig.icon} {risk.risk_level}
          </span>
          <AnimatePresence>
            {risk.kill_switch_active && (
              <motion.span
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                exit={{ scale: 0 }}
                className="rounded-full border border-rose-600/50 bg-rose-600/20 px-2 py-0.5 text-[10px] font-bold text-rose-300"
              >
                KILL ACTIVE
              </motion.span>
            )}
          </AnimatePresence>
        </div>
      }
    >
      <div className="space-y-3">
        <BarMeter
          value={risk.current_drawdown}
          max={risk.max_drawdown}
          label="Drawdown"
          color={risk.current_drawdown > 0.1 ? "rose" : "amber"}
        />
        <BarMeter
          value={risk.current_exposure}
          max={risk.max_exposure}
          label="Exposure"
          color="cyan"
        />
        <BarMeter
          value={risk.daily_loss_pct}
          max={0.05}
          label="Daily Loss Limit"
          color={risk.daily_loss_pct > 0.03 ? "rose" : "emerald"}
        />

        <div className="rounded-lg border border-white/6 bg-slate-950/50 p-2">
          <p className="mb-1 text-[10px] uppercase tracking-widest text-slate-500">
            Drawdown History
          </p>
          <DrawdownSparkline values={drawdownHistory} />
        </div>

        <div className="grid grid-cols-3 gap-2 text-center">
          <div>
            <p className="text-[10px] text-slate-500">VaR</p>
            <p
              className={`font-mono text-xs font-semibold ${risk.var_breach ? "text-rose-400" : "text-emerald-400"}`}
            >
              {risk.var_breach ? "BREACH" : "OK"}
            </p>
          </div>
          <div>
            <p className="text-[10px] text-slate-500">Positions</p>
            <p className="font-mono text-xs font-semibold text-slate-200">
              {risk.open_positions}/{risk.max_open_trades}
            </p>
          </div>
          <div>
            <p className="text-[10px] text-slate-500">Kill Switch</p>
            <p
              className={`font-mono text-xs font-semibold ${risk.kill_switch_active ? "text-rose-400" : "text-emerald-400"}`}
            >
              {risk.kill_switch_active ? "ACTIVE" : "ARMED"}
            </p>
          </div>
        </div>
      </div>
    </TerminalCard>
  );
}
