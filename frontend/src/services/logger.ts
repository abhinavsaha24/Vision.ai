type LogLevel = "debug" | "info" | "warn" | "error";

interface LogPayload {
  message: string;
  context?: Record<string, unknown>;
  error?: unknown;
}

const LEVEL_ORDER: Record<LogLevel, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
};

function resolveLevel(): LogLevel {
  const raw = process.env.NEXT_PUBLIC_LOG_LEVEL?.toLowerCase();
  if (raw === "debug" || raw === "info" || raw === "warn" || raw === "error") {
    return raw;
  }
  return "info";
}

const threshold = resolveLevel();

function shouldLog(level: LogLevel) {
  return LEVEL_ORDER[level] >= LEVEL_ORDER[threshold];
}

function stamp(level: LogLevel, payload: LogPayload) {
  return {
    ts: new Date().toISOString(),
    level,
    message: payload.message,
    context: payload.context,
    error: payload.error,
  };
}

export const logger = {
  debug(payload: LogPayload) {
    if (!shouldLog("debug")) return;
    console.debug("[vision-ai]", stamp("debug", payload));
  },
  info(payload: LogPayload) {
    if (!shouldLog("info")) return;
    console.info("[vision-ai]", stamp("info", payload));
  },
  warn(payload: LogPayload) {
    if (!shouldLog("warn")) return;
    console.warn("[vision-ai]", stamp("warn", payload));
  },
  error(payload: LogPayload) {
    if (!shouldLog("error")) return;
    console.error("[vision-ai]", stamp("error", payload));
  },
};
