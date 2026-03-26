import { apiClient, apiService } from "@/services/api";

export interface StrategyDescriptor {
  name: string;
  key: string;
  active: boolean;
  weight: number;
  type: string;
  thresholds?: {
    long?: number;
    short?: number;
    min_confidence?: number;
  };
}

export interface SystemReadiness {
  overall_score?: number;
  score?: number;
  [key: string]: unknown;
}

export interface WorkerStatusResponse {
  total_workers?: number;
  running?: number;
  workers?: Record<string, unknown>;
}

export const controlApi = {
  async getSystemReadiness() {
    const { data } = await apiClient.get<SystemReadiness>("/system/readiness");
    return data;
  },

  async getSystemPerformance() {
    const { data } = await apiClient.get("/system/performance");
    return data;
  },

  async getSystemRisk(symbol = "BTC/USDT") {
    const { data } = await apiClient.get("/system/risk", {
      params: { symbol },
    });
    return data;
  },

  async getMetaAlpha(symbol: string, horizon = 5) {
    const { data } = await apiClient.get("/system/meta_alpha", {
      params: { symbol, horizon },
    });
    return data;
  },

  async getStrategies() {
    const { data } = await apiClient.get<{ strategies: StrategyDescriptor[] }>(
      "/strategies/list",
    );
    return data.strategies ?? [];
  },

  async startStrategy(strategyName: string) {
    const { data } = await apiClient.post("/strategy/start", {
      strategy_name: strategyName,
    });
    return data;
  },

  async stopStrategy(strategyName: string) {
    const { data } = await apiClient.post("/strategy/stop", {
      strategy_name: strategyName,
    });
    return data;
  },

  async getWorkersStatus() {
    const { data } =
      await apiClient.get<WorkerStatusResponse>("/workers/status");
    return data;
  },

  async getPaperStatus() {
    return apiService.getPaperStatus();
  },

  async startEngine(
    symbol: string,
    initialCash: number,
    intervalSeconds: number,
  ) {
    return apiService.startPaperTrading(symbol, initialCash, intervalSeconds);
  },

  async stopEngine() {
    return apiService.stopPaperTrading();
  },

  async enableLiveTrading() {
    const { data } = await apiClient.post("/live-trading/enable");
    return data;
  },

  async runManual(side: "buy" | "sell", symbol: string, sizeUsd: number) {
    const key = apiService.generateIdempotencyKey(`control-${side}`);
    if (side === "buy") {
      return apiService.manualBuy(symbol, sizeUsd, key);
    }
    return apiService.manualSell(symbol, sizeUsd, key);
  },

  async closePosition(symbol: string) {
    const key = apiService.generateIdempotencyKey("control-close");
    return apiService.closePosition(symbol, key);
  },

  async emergencyKill(reason = "manual_terminal_override") {
    return apiService.emergencyKill(reason);
  },

  async emergencyKillReset() {
    return apiService.emergencyKillReset();
  },

  async getOrders(limit = 120) {
    const [history, active] = await Promise.all([
      apiService.getOrderHistory(limit),
      apiClient.get("/orders/active").then((result) => result.data),
    ]);

    return {
      historyOrders: (history?.orders ?? []) as Record<string, unknown>[],
      activeOrders: (active?.orders ?? []) as Record<string, unknown>[],
    };
  },

  async getModelRegistry() {
    const { data } = await apiClient.get("/model/registry");
    return data;
  },
};
