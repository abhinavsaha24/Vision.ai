import { getAuthToken } from "@/store/authStore";

export type ChannelName = "market" | "signals" | "portfolio" | "metrics";

export interface StreamEnvelope<T> {
  type: "data" | "heartbeat" | "ping" | "pong";
  channel?: string;
  symbol?: string;
  seq?: number;
  server_ts?: string;
  data?: T;
}

export interface ChannelConfig {
  channel: ChannelName;
  symbol?: string;
}

type Subscriber<T> = (payload: T) => void;
type StatusSubscriber = (connected: boolean) => void;

function resolveWsBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_WS_URL;
  if (configured && configured.trim()) return configured.replace(/\/$/, "");

  const apiConfigured = process.env.NEXT_PUBLIC_API_URL;
  if (apiConfigured && apiConfigured.trim()) {
    return apiConfigured
      .replace(/^http:\/\//i, "ws://")
      .replace(/^https:\/\//i, "wss://")
      .replace(/\/$/, "");
  }

  if (typeof window !== "undefined" && window.location) {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    return `${protocol}://${window.location.host}`;
  }

  return "ws://127.0.0.1:10000";
}

function endpointFor(channel: ChannelName): string {
  if (channel === "market") return "/ws/market";
  if (channel === "signals") return "/ws/signals";
  if (channel === "portfolio") return "/ws/portfolio";
  return "/ws/metrics";
}

class RealtimeChannel<T> {
  private ws: WebSocket | null = null;
  private readonly subscribers = new Set<Subscriber<T>>();
  private readonly statusSubscribers = new Set<StatusSubscriber>();
  private reconnectDelayMs = 1200;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private lastMessageAt = 0;
  private lastSequence = 0;
  private closedByUser = false;

  constructor(private readonly config: ChannelConfig) {}

  private buildUrl(): string {
    const base = resolveWsBaseUrl();
    const token = getAuthToken();
    const params = new URLSearchParams();
    if (this.config.symbol) params.set("symbol", this.config.symbol);
    if (token) params.set("token", token);
    const query = params.toString();
    return `${base}${endpointFor(this.config.channel)}${query ? `?${query}` : ""}`;
  }

  private notifyStatus(connected: boolean) {
    this.statusSubscribers.forEach((subscriber) => subscriber(connected));
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
  }

  private connect() {
    const url = this.buildUrl();
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      this.reconnectDelayMs = 1200;
      this.lastMessageAt = Date.now();
      this.lastSequence = 0;
      this.notifyStatus(true);
      this.heartbeatTimer = setInterval(() => {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;

        if (Date.now() - this.lastMessageAt > 70000) {
          this.ws.close(4000, "heartbeat timeout");
          return;
        }

        this.ws.send(
          JSON.stringify({ type: "ping", client_ts: new Date().toISOString() }),
        );
      }, 15000);
    };

    this.ws.onmessage = (event) => {
      try {
        this.lastMessageAt = Date.now();
        const message = JSON.parse(event.data) as StreamEnvelope<T>;

        if (message.type === "heartbeat") {
          if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(
              JSON.stringify({
                type: "pong",
                client_ts: new Date().toISOString(),
              }),
            );
          }
          return;
        }

        if (
          (message.seq ?? 0) <= this.lastSequence &&
          message.seq !== undefined
        ) {
          return;
        }
        if (message.seq !== undefined) {
          this.lastSequence = message.seq;
        }

        const payload =
          message.type === "data" && message.data !== undefined
            ? message.data
            : (message as unknown as T);
        this.subscribers.forEach((subscriber) => subscriber(payload));
      } catch {
        // Ignore malformed messages and keep stream alive.
      }
    };

    this.ws.onclose = () => {
      this.notifyStatus(false);
      this.clearTimers();
      if (this.closedByUser) return;
      this.reconnectTimer = setTimeout(
        () => {
          this.reconnectDelayMs = Math.min(this.reconnectDelayMs * 1.8, 30000);
          this.connect();
        },
        this.reconnectDelayMs + Math.floor(Math.random() * 200),
      );
    };

    this.ws.onerror = () => {
      this.notifyStatus(false);
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
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.notifyStatus(false);
  }

  subscribe(subscriber: Subscriber<T>) {
    this.subscribers.add(subscriber);
    return () => this.subscribers.delete(subscriber);
  }

  subscribeStatus(subscriber: StatusSubscriber) {
    this.statusSubscribers.add(subscriber);
    return () => this.statusSubscribers.delete(subscriber);
  }
}

export function createRealtimeChannel<T>(
  config: ChannelConfig,
): RealtimeChannel<T> {
  return new RealtimeChannel<T>(config);
}
