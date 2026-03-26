import axios, { AxiosError } from "axios";
import { getAuthToken } from "@/store/authStore";

function resolveApiBaseUrl(): string {
  const internal = process.env.NEXT_INTERNAL_API_URL?.trim();
  const configured = process.env.NEXT_PUBLIC_API_URL?.trim();

  if (typeof window !== "undefined") {
    // Keep browser traffic on same-origin Next route handlers.
    return `${window.location.origin}/api`;
  }

  if (internal) return internal.replace(/\/$/, "");
  if (configured) return configured.replace(/\/$/, "");
  return "http://api-service:8080";
}

export const apiClient = axios.create({
  baseURL: resolveApiBaseUrl(),
  timeout: 30000,
  headers: { "Content-Type": "application/json" },
});

apiClient.interceptors.request.use((config) => {
  const token = getAuthToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as
      | (typeof error.config & {
          _retryCount?: number;
        })
      | null;

    const status = error.response?.status;
    const isNetworkError = !error.response;
    const canRetry = isNetworkError || (status !== undefined && status >= 500);

    if (config && canRetry) {
      const retryCount = config._retryCount ?? 0;
      if (retryCount < 2) {
        config._retryCount = retryCount + 1;
        const delay =
          250 * Math.pow(2, retryCount) + Math.floor(Math.random() * 120);
        await new Promise((resolve) => setTimeout(resolve, delay));
        return apiClient.request(config);
      }
    }

    const hasToken = Boolean(getAuthToken());
    const requestUrl = String(error.config?.url ?? "");
    const isAuthRoute =
      requestUrl.includes("/auth/login") || requestUrl.includes("/auth/signup");

    // Only expire active sessions for protected API calls.
    if (
      status === 401 &&
      hasToken &&
      !isAuthRoute &&
      typeof window !== "undefined"
    ) {
      window.dispatchEvent(new CustomEvent("vision-ai-auth-expired"));
    }
    return Promise.reject(error);
  },
);

export interface LoginResponse {
  access_token?: string;
  token?: string;
  token_type?: string;
}

export interface Kline {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface MarketHistoryResponse {
  symbol: string;
  timeframe: string;
  candles: Kline[];
}

export interface RealtimeMarket {
  symbol: string;
  last_price: number;
  mid_price: number;
  spread_bps: number;
  order_book_imbalance: number;
  volume_delta?: number;
  volatility_expansion?: number;
  stale: boolean;
  bids: [number, number][];
  asks: [number, number][];
}

export interface PredictionResponse {
  symbol: string;
  signal: "BUY" | "SELL" | "HOLD";
  alpha_score: number;
  signal_confidence: number;
  position_size: number;
  regime?: { market_state?: string; trend?: string; volatility?: string };
  strategy?: { strategy_name?: string };
  market_snapshot?: RealtimeMarket;
}

export interface PortfolioResponse {
  current_equity?: number;
  cash?: number;
  positions_value?: number;
  unrealized_pnl?: number;
  total_return?: number;
  win_rate?: number;
  sharpe_ratio?: number;
  max_drawdown?: number;
  total_trades?: number;
}

export const apiService = {
  generateIdempotencyKey(prefix = "manual") {
    const g = globalThis as { crypto?: { randomUUID?: () => string } };
    if (g.crypto?.randomUUID) {
      return `${prefix}-${g.crypto.randomUUID()}`;
    }
    return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  },

  async login(email: string, password: string) {
    const { data } = await apiClient.post<LoginResponse>("/auth/login", {
      email,
      password,
    });
    return data;
  },

  async signup(email: string, password: string) {
    const { data } = await apiClient.post("/auth/signup", {
      email,
      password,
    });
    return data;
  },

  async getMe() {
    const { data } = await apiClient.get("/auth/me");
    return data;
  },

  async getMeWithToken(token: string) {
    const { data } = await apiClient.get("/auth/me", {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
    return data;
  },

  async getHealth() {
    const { data } = await apiClient.get("/health");
    return data;
  },

  async getSystemReadiness() {
    const { data } = await apiClient.get("/system/readiness");
    return data;
  },

  async getMarketHistory(symbol: string, timeframe = "1m", limit = 300) {
    const { data } = await apiClient.get<MarketHistoryResponse>(
      "/market/history",
      {
        params: { symbol, timeframe, limit },
      },
    );
    return data;
  },

  async getPrediction(symbol: string, horizon = 5) {
    const { data } = await apiClient.post<PredictionResponse>(
      "/model/predict",
      {
        symbol,
        horizon,
      },
    );
    return data;
  },

  async getPortfolioPerformance() {
    const { data } = await apiClient.get<PortfolioResponse>(
      "/portfolio/performance",
    );
    return data;
  },

  async getPaperStatus() {
    const { data } = await apiClient.get("/paper-trading/status");
    return data;
  },

  async startPaperTrading(
    symbol: string,
    initial_cash = 10000,
    interval_seconds = 15,
  ) {
    const { data } = await apiClient.post("/paper-trading/start", {
      symbol,
      initial_cash,
      interval_seconds,
    });
    return data;
  },

  async stopPaperTrading() {
    const { data } = await apiClient.post("/paper-trading/stop");
    return data;
  },

  async getLiveTradingReadiness() {
    const { data } = await apiClient.get("/live-trading/readiness");
    return data;
  },

  async enableLiveTrading() {
    const { data } = await apiClient.post("/live-trading/enable");
    return data;
  },

  async manualBuy(symbol: string, size_usd: number, idempotency_key: string) {
    const { data } = await apiClient.post("/trading/buy", {
      symbol,
      size_usd,
      side: "buy",
      idempotency_key,
    });
    return data;
  },

  async manualSell(symbol: string, size_usd: number, idempotency_key: string) {
    const { data } = await apiClient.post("/trading/sell", {
      symbol,
      size_usd,
      side: "sell",
      idempotency_key,
    });
    return data;
  },

  async closePosition(symbol: string, idempotency_key: string) {
    const { data } = await apiClient.post("/trading/close", {
      symbol,
      idempotency_key,
    });
    return data;
  },

  async emergencyKill(reason = "manual_emergency") {
    const { data } = await apiClient.post("/emergency/kill", null, {
      params: { reason },
    });
    return data;
  },

  async emergencyKillReset() {
    const { data } = await apiClient.post("/emergency/kill/reset");
    return data;
  },

  async getOrderHistory(limit = 50) {
    const { data } = await apiClient.get("/orders/history", {
      params: { limit },
    });
    return data;
  },
};
