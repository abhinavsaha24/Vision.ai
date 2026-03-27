"use client";

import { useEffect, useRef, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { TerminalCard } from "@/components/ui/terminal-card";

export type ActivityType = "trade" | "signal" | "system" | "risk" | "error";

export interface ActivityEvent {
  id: string;
  type: ActivityType;
  timestamp: string;
  message: string;
  details?: string;
}

interface ActivityStreamProps {
  events: ActivityEvent[];
  maxEvents?: number;
}

const TYPE_CONFIG: Record<
  ActivityType,
  { label: string; dotColor: string; textColor: string }
> = {
  trade: {
    label: "TRADE",
    dotColor: "bg-cyan-400",
    textColor: "text-cyan-300",
  },
  signal: {
    label: "SIGNAL",
    dotColor: "bg-purple-400",
    textColor: "text-purple-300",
  },
  system: {
    label: "SYS",
    dotColor: "bg-slate-400",
    textColor: "text-slate-300",
  },
  risk: {
    label: "RISK",
    dotColor: "bg-amber-400",
    textColor: "text-amber-300",
  },
  error: {
    label: "ERR",
    dotColor: "bg-rose-400",
    textColor: "text-rose-300",
  },
};

function formatTime(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return "--:--:--";
  }
}

function EventRow({ event }: { event: ActivityEvent }) {
  const config = TYPE_CONFIG[event.type] || TYPE_CONFIG.system;

  return (
    <motion.div
      initial={{ opacity: 0, x: -12 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 12 }}
      transition={{ duration: 0.25 }}
      className="flex items-start gap-2 border-b border-white/[0.04] py-1.5 last:border-b-0"
    >
      {/* Dot */}
      <div className="mt-1 flex-shrink-0">
        <div className={`h-1.5 w-1.5 rounded-full ${config.dotColor}`} />
      </div>

      {/* Timestamp */}
      <span className="flex-shrink-0 font-mono text-[10px] text-slate-600">
        {formatTime(event.timestamp)}
      </span>

      {/* Type badge */}
      <span
        className={`flex-shrink-0 rounded px-1 py-0 text-[9px] font-bold tracking-widest ${config.textColor} bg-white/[0.04]`}
      >
        {config.label}
      </span>

      {/* Message */}
      <span className="flex-1 text-[11px] leading-tight text-slate-300">
        {event.message}
        {event.details && (
          <span className="ml-1 text-slate-500">{event.details}</span>
        )}
      </span>
    </motion.div>
  );
}

export function ActivityStream({
  events,
  maxEvents = 100,
}: ActivityStreamProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  const displayEvents = useMemo(
    () => events.slice(-maxEvents).reverse(),
    [events, maxEvents],
  );

  // Auto-scroll to top on new events
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [events.length]);

  const counts = useMemo(() => {
    const c: Partial<Record<ActivityType, number>> = {};
    for (const e of events) {
      c[e.type] = (c[e.type] || 0) + 1;
    }
    return c;
  }, [events]);

  return (
    <TerminalCard
      title="Activity Stream"
      right={
        <div className="flex items-center gap-2">
          {(["trade", "signal", "risk", "error"] as ActivityType[]).map(
            (type) =>
              (counts[type] || 0) > 0 && (
                <span
                  key={type}
                  className={`rounded px-1.5 py-0 text-[9px] font-bold tracking-wider ${TYPE_CONFIG[type].textColor} bg-white/[0.04]`}
                >
                  {TYPE_CONFIG[type].label} {counts[type]}
                </span>
              ),
          )}
        </div>
      }
    >
      <div
        ref={scrollRef}
        className="max-h-52 space-y-0 overflow-auto rounded-lg border border-white/6 bg-slate-950/55 p-2"
      >
        {displayEvents.length === 0 && (
          <p className="py-4 text-center text-[11px] text-slate-600">
            No activity yet. Stream will populate in real-time...
          </p>
        )}
        <AnimatePresence mode="popLayout">
          {displayEvents.map((event) => (
            <EventRow key={event.id} event={event} />
          ))}
        </AnimatePresence>
      </div>
    </TerminalCard>
  );
}
