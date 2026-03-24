import axios, { AxiosError } from "axios";
import { getAuthToken } from "@/store/authStore";

function resolveApiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_URL;
  if (configured && configured.trim()) {
    return configured.replace(/\/$/, "");
  }

  if (typeof window !== "undefined" && window.location) {
    return `${window.location.protocol}//${window.location.host}`.replace(
      /\/$/,
      "",
    );
  }

  return "";
}

const apiClient = axios.create({
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
  (error: AxiosError) => {
    if (error.response?.status === 401 && typeof window !== "undefined") {
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
  async login(email: string, password: string) {
    const { data } = await apiClient.post<LoginResponse>("/auth/login", {
      email,
      password,
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

  async manualBuy(symbol: string, size_usd: number) {
    const { data } = await apiClient.post("/trading/buy", {
      symbol,
      size_usd,
      side: "buy",
    });
    return data;
  },

  async manualSell(symbol: string, size_usd: number) {
    const { data } = await apiClient.post("/trading/sell", {
      symbol,
      size_usd,
      side: "sell",
    });
    return data;
  },

  async closePosition(symbol: string) {
    const { data } = await apiClient.post("/trading/close", { symbol });
    return data;
  },

  async getOrderHistory(limit = 50) {
    const { data } = await apiClient.get("/orders/history", {
      params: { limit },
    });
    return data;
  },
};
