import { getAuthToken } from "@/store/authStore";
import { logger } from "@/services/logger";

export type StreamChannel =
  | "market"
  | "signals"
  | "portfolio"
  | "metrics"
  | "live";

interface StreamEnvelope<TPayload> {
  type: "data" | "heartbeat" | "ping" | "pong";
  channel?: string;
  symbol?: string;
  seq?: number;
  server_ts?: string;
  data?: TPayload;
}

export interface StreamStatus {
  channel: StreamChannel;
  connected: boolean;
  reconnectCount: number;
  seqGapCount: number;
  averageLatencyMs: number;
  throughputPerSecond: number;
  lastMessageAt: number | null;
}

interface StreamManagerConfig {
  channel: StreamChannel;
  symbol?: string;
}

type PayloadSubscriber<TPayload> = (payloads: TPayload[]) => void;
type StatusSubscriber = (status: StreamStatus) => void;

function isLoopbackHost(hostname: string): boolean {
  const host = hostname.toLowerCase();
  return host === "localhost" || host === "127.0.0.1" || host === "::1";
}

function normalizeLoopbackBase(baseUrl: string): string {
  if (typeof window === "undefined") return baseUrl;
  try {
    const parsed = new URL(baseUrl);
    const browserHost = window.location.hostname;
    if (isLoopbackHost(parsed.hostname) && isLoopbackHost(browserHost)) {
      parsed.hostname = browserHost;
      return parsed.toString().replace(/\/$/, "");
    }
    return baseUrl;
  } catch {
    return baseUrl;
  }
}

function shouldRejectLoopbackCandidate(baseUrl: string): boolean {
  if (typeof window === "undefined") return false;
  try {
    const parsed = new URL(baseUrl);
    const browserHost = window.location.hostname;
    return !isLoopbackHost(browserHost) && isLoopbackHost(parsed.hostname);
  } catch {
    return false;
  }
}

function resolveWsBaseUrl(): string {
  const internal = process.env.NEXT_INTERNAL_WS_URL;
  if (internal?.trim()) {
    const candidate = normalizeLoopbackBase(internal.replace(/\/$/, ""));
    if (!shouldRejectLoopbackCandidate(candidate)) return candidate;
  }

  const configured = process.env.NEXT_PUBLIC_WS_URL;
  if (configured?.trim()) {
    const candidate = normalizeLoopbackBase(configured.replace(/\/$/, ""));
    if (!shouldRejectLoopbackCandidate(candidate)) return candidate;
  }

  const apiConfigured = process.env.NEXT_PUBLIC_API_URL;
  if (apiConfigured?.trim()) {
    const candidate = normalizeLoopbackBase(
      apiConfigured
        .replace(/^http:\/\//i, "ws://")
        .replace(/^https:\/\//i, "wss://")
        .replace(/\/$/, ""),
    );
    if (!shouldRejectLoopbackCandidate(candidate)) return candidate;
  }

  if (typeof window !== "undefined" && window.location) {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    return `${protocol}://${window.location.host}`;
  }

  return "ws://api-service:8080";
}

function channelPath(channel: StreamChannel) {
  if (channel === "market") return "/ws/market";
  if (channel === "signals") return "/ws/signals";
  if (channel === "portfolio") return "/ws/portfolio";
  if (channel === "metrics") return "/ws/metrics";
  return "/ws/live";
}

function isLikelyJwtToken(token: string | null): token is string {
  if (!token) return false;
  const parts = token.split(".");
  return parts.length === 3 && parts.every((part) => part.length > 0);
}

function buildProtocols(token: string | null): string[] {
  const protocols = ["vision-ai.v1"];
  if (isLikelyJwtToken(token)) {
    protocols.push(`bearer.${token}`);
  }
  return protocols;
}

export class StreamManager<TPayload> {
  private ws: WebSocket | null = null;
  private readonly payloadSubscribers = new Set<PayloadSubscriber<TPayload>>();
  private readonly statusSubscribers = new Set<StatusSubscriber>();
  private readonly messageQueue: TPayload[] = [];
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private throughputTimer: ReturnType<typeof setInterval> | null = null;
  private rafToken: number | null = null;
  private reconnectDelayMs = 900;
  private closedByUser = false;
  private throughputCounter = 0;
  private latencySamples: number[] = [];
  private lastSeq = 0;
  private status: StreamStatus;

  constructor(private readonly config: StreamManagerConfig) {
    this.status = {
      channel: config.channel,
      connected: false,
      reconnectCount: 0,
      seqGapCount: 0,
      averageLatencyMs: 0,
      throughputPerSecond: 0,
      lastMessageAt: null,
    };
  }

  private notifyStatus() {
    this.statusSubscribers.forEach((subscriber) =>
      subscriber({ ...this.status }),
    );
  }

  private setStatus(next: Partial<StreamStatus>) {
    this.status = { ...this.status, ...next };
    this.notifyStatus();
  }

  private buildUrl() {
    const token = getAuthToken();
    const params = new URLSearchParams();
    if (
      (process.env.NEXT_PUBLIC_WS_QUERY_TOKEN_FALLBACK || "").toLowerCase() ===
        "true" &&
      isLikelyJwtToken(token)
    ) {
      params.set("token", token);
    }
    if (this.config.symbol) params.set("symbol", this.config.symbol);
    const query = params.toString();
    return `${resolveWsBaseUrl()}${channelPath(this.config.channel)}${query ? `?${query}` : ""}`;
  }

  private clearTimers() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    if (this.throughputTimer) {
      clearInterval(this.throughputTimer);
      this.throughputTimer = null;
    }
    if (this.rafToken !== null && typeof window !== "undefined") {
      window.cancelAnimationFrame(this.rafToken);
      this.rafToken = null;
    }
  }

  private flushQueue() {
    this.rafToken = null;
    if (this.messageQueue.length === 0) return;
    const payloads = this.messageQueue.splice(0, this.messageQueue.length);
    this.payloadSubscribers.forEach((subscriber) => subscriber(payloads));
  }

  private scheduleFlush() {
    if (this.rafToken !== null) return;
    if (typeof window !== "undefined") {
      this.rafToken = window.requestAnimationFrame(() => this.flushQueue());
      return;
    }
    this.rafToken = 0;
    setTimeout(() => this.flushQueue(), 16);
  }

  private scheduleReconnect() {
    if (this.closedByUser) return;
    this.reconnectTimer = setTimeout(
      () => {
        this.reconnectDelayMs = Math.min(this.reconnectDelayMs * 1.8, 30000);
        this.setStatus({ reconnectCount: this.status.reconnectCount + 1 });
        this.connect();
      },
      this.reconnectDelayMs + Math.floor(Math.random() * 250),
    );
  }

  private connect() {
    const url = this.buildUrl();
    const token = getAuthToken();
    try {
      this.ws = new WebSocket(url, buildProtocols(token));
    } catch (error) {
      logger.error({
        message: "WebSocket initialization failed",
        context: { url },
        error,
      });
      this.setStatus({ connected: false });
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.reconnectDelayMs = 900;
      this.lastSeq = 0;
      this.latencySamples = [];
      this.throughputCounter = 0;
      this.setStatus({
        connected: true,
        lastMessageAt: Date.now(),
        throughputPerSecond: 0,
        averageLatencyMs: 0,
      });

      this.heartbeatTimer = setInterval(() => {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
        this.ws.send(
          JSON.stringify({ type: "ping", client_ts: new Date().toISOString() }),
        );
      }, 15000);

      this.throughputTimer = setInterval(() => {
        this.setStatus({ throughputPerSecond: this.throughputCounter });
        this.throughputCounter = 0;
      }, 1000);
    };

    this.ws.onmessage = (event) => {
      this.throughputCounter += 1;
      this.setStatus({ lastMessageAt: Date.now() });

      try {
        const parsed = JSON.parse(event.data) as StreamEnvelope<TPayload>;
        if (parsed.type === "heartbeat") {
          if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(
              JSON.stringify({
                type: "pong",
                client_ts: new Date().toISOString(),
              }),
            );
          }
          return;
        }

        if (typeof parsed.seq === "number") {
          if (this.lastSeq > 0 && parsed.seq - this.lastSeq > 1) {
            this.setStatus({ seqGapCount: this.status.seqGapCount + 1 });
          }
          this.lastSeq = parsed.seq;
        }

        if (parsed.server_ts) {
          const latency = Date.now() - new Date(parsed.server_ts).getTime();
          if (Number.isFinite(latency) && latency >= 0) {
            this.latencySamples = [...this.latencySamples.slice(-59), latency];
            const average =
              this.latencySamples.reduce((sum, value) => sum + value, 0) /
              this.latencySamples.length;
            this.setStatus({ averageLatencyMs: Math.round(average) });
          }
        }

        const payload =
          parsed.type === "data" && parsed.data !== undefined
            ? parsed.data
            : (parsed as unknown as TPayload);
        this.messageQueue.push(payload);
        this.scheduleFlush();
      } catch (error) {
        logger.warn({
          message: "Ignored malformed websocket payload",
          context: { channel: this.config.channel },
          error,
        });
      }
    };

    this.ws.onclose = (event) => {
      this.setStatus({ connected: false });
      this.clearTimers();
      // Authentication failures should force a clean re-login instead of reconnect churn.
      // 4001 is emitted by backend websocket auth guard.
      if (event.code === 4001) {
        if (typeof window !== "undefined") {
          window.dispatchEvent(new CustomEvent("vision-ai-auth-expired"));
        }
        return;
      }
      this.scheduleReconnect();
    };

    this.ws.onerror = (error) => {
      logger.warn({
        message: "WebSocket error",
        context: { channel: this.config.channel },
        error,
      });
      this.setStatus({ connected: false });
    };
  }

  start() {
    this.closedByUser = false;
    if (
      this.ws &&
      (this.ws.readyState === WebSocket.OPEN ||
        this.ws.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }
    this.connect();
  }

  stop() {
    this.closedByUser = true;
    this.clearTimers();
    this.messageQueue.splice(0, this.messageQueue.length);
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.setStatus({ connected: false, throughputPerSecond: 0 });
  }

  subscribePayload(subscriber: PayloadSubscriber<TPayload>) {
    this.payloadSubscribers.add(subscriber);
    return () => this.payloadSubscribers.delete(subscriber);
  }

  subscribeStatus(subscriber: StatusSubscriber) {
    this.statusSubscribers.add(subscriber);
    subscriber({ ...this.status });
    return () => this.statusSubscribers.delete(subscriber);
  }
}
