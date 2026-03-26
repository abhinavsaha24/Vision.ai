"use client";

import { create } from "zustand";
import type { StrategyDescriptor } from "@/services/api/controlApi";
import type { StreamStatus } from "@/services/websocket/streamManager";

export interface MarketDepthLevel {
  price: number;
  size: number;
  total?: number;
}

export interface TradePrint {
  id: string;
  price: number;
  size: number;
  side: "buy" | "sell" | "unknown";
  ts: string;
}

export interface MarketState {
  symbol: string;
  lastPrice: number;
  midPrice: number;
  spreadBps: number;
  spread: number;
  imbalance: number;
  bids: MarketDepthLevel[];
  asks: MarketDepthLevel[];
  stale: boolean;
}

export interface SignalState {
  symbol: string;
  direction: "BUY" | "SELL" | "HOLD";
  confidence: number;
  probability: number;
  alphaScore: number;
  regime: string;
  marketState: string;
  strategy: string;
  timestamp: string;
}

export interface SignalLifecycleEntry {
  id: string;
  stage: "trigger" | "execution" | "outcome";
  direction: "BUY" | "SELL" | "HOLD";
  ts: string;
  score: number;
  notes: string;
}

export interface PortfolioState {
  timestamp: string;
  cash: number;
  equity: number;
  unrealizedPnl: number;
  realizedPnl: number;
  totalReturn: number;
  positions: Record<string, unknown>;
}

export interface MetricsState {
  timestamp: string;
  winRate: number;
  sharpeRatio: number;
  maxDrawdown: number;
  totalTrades: number;
  profitableTrades: number;
  avgWin: number;
  avgLoss: number;
}

export interface ExecutionRecord {
  id: string;
  timestamp: string;
  symbol: string;
  side: string;
  size: number;
  price: number;
  status: string;
  venue: string;
  expectedPrice?: number;
  route?: string;
}

export interface HealthState {
  reconnectCount: number;
  avgLatencyMs: number;
  seqGapCount: number;
  throughputPerSecond: number;
  channelStatus: Record<string, StreamStatus>;
}

interface ControlSystemState {
  symbol: string;
  market: MarketState;
  signal: SignalState;
  portfolio: PortfolioState;
  metrics: MetricsState;
  tradeTape: TradePrint[];
  signalLifecycle: SignalLifecycleEntry[];
  executions: ExecutionRecord[];
  activeExecutions: ExecutionRecord[];
  health: HealthState;
  systemReadinessScore: number;
  riskState: Record<string, unknown>;
  metaAlpha: Record<string, unknown>;
  strategies: StrategyDescriptor[];
  engineState: Record<string, unknown>;
  logs: string[];
  setSymbol: (symbol: string) => void;
  appendLog: (line: string) => void;
  ingestMarket: (payload: Record<string, unknown>) => void;
  ingestSignal: (payload: Record<string, unknown>) => void;
  ingestPortfolio: (payload: Record<string, unknown>) => void;
  ingestMetrics: (payload: Record<string, unknown>) => void;
  setExecutions: (
    history: Record<string, unknown>[],
    active: Record<string, unknown>[],
  ) => void;
  setHealthStatus: (status: StreamStatus) => void;
  setSystemReadinessScore: (score: number) => void;
  setRiskState: (riskState: Record<string, unknown>) => void;
  setMetaAlpha: (metaAlpha: Record<string, unknown>) => void;
  setStrategies: (strategies: StrategyDescriptor[]) => void;
  setEngineState: (engineState: Record<string, unknown>) => void;
}

const initialMarket: MarketState = {
  symbol: "BTCUSDT",
  lastPrice: 0,
  midPrice: 0,
  spreadBps: 0,
  spread: 0,
  imbalance: 0,
  bids: [],
  asks: [],
  stale: true,
};

const initialSignal: SignalState = {
  symbol: "BTCUSDT",
  direction: "HOLD",
  confidence: 0,
  probability: 0,
  alphaScore: 0,
  regime: "UNKNOWN",
  marketState: "UNKNOWN",
  strategy: "alpha_model",
  timestamp: new Date().toISOString(),
};

const initialPortfolio: PortfolioState = {
  timestamp: new Date().toISOString(),
  cash: 0,
  equity: 0,
  unrealizedPnl: 0,
  realizedPnl: 0,
  totalReturn: 0,
  positions: {},
};

const initialMetrics: MetricsState = {
  timestamp: new Date().toISOString(),
  winRate: 0,
  sharpeRatio: 0,
  maxDrawdown: 0,
  totalTrades: 0,
  profitableTrades: 0,
  avgWin: 0,
  avgLoss: 0,
};

function normalizeDepth(raw: unknown): MarketDepthLevel[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((level) => {
      if (!Array.isArray(level) || level.length < 2) return null;
      const price = Number(level[0]);
      const size = Number(level[1]);
      if (!Number.isFinite(price) || !Number.isFinite(size)) return null;
      return { price, size };
    })
    .filter((level): level is MarketDepthLevel => level !== null)
    .slice(0, 120);
}

function deriveTradePrints(payload: Record<string, unknown>): TradePrint[] {
  const bucket = payload.trades ?? payload.recent_trades;
  if (!Array.isArray(bucket)) return [];

  return bucket
    .map((trade, index) => {
      if (typeof trade !== "object" || trade === null) return null;
      const row = trade as Record<string, unknown>;
      const sideRaw = String(
        row.side ?? row.aggressor ?? row.direction ?? "unknown",
      ).toLowerCase();
      const side: TradePrint["side"] = sideRaw.includes("buy")
        ? "buy"
        : sideRaw.includes("sell")
          ? "sell"
          : "unknown";

      return {
        id: String(row.id ?? `${Date.now()}-${index}`),
        price: Number(row.price ?? row.p ?? 0),
        size: Number(row.size ?? row.qty ?? row.q ?? 0),
        side,
        ts: String(row.ts ?? row.time ?? new Date().toISOString()),
      };
    })
    .filter((trade): trade is TradePrint => trade !== null)
    .filter((trade) => Number.isFinite(trade.price));
}

function parseExecutionRow(raw: Record<string, unknown>): ExecutionRecord {
  return {
    id: String(raw.id ?? raw.order_id ?? crypto.randomUUID()),
    timestamp: String(raw.timestamp ?? raw.ts ?? new Date().toISOString()),
    symbol: String(raw.symbol ?? "UNKNOWN"),
    side: String(raw.side ?? "unknown"),
    size: Number(raw.size ?? raw.quantity ?? 0),
    price: Number(raw.price ?? raw.fill_price ?? 0),
    status: String(raw.status ?? "unknown"),
    venue: String(raw.venue ?? raw.exchange ?? "sim"),
    expectedPrice: Number(raw.expected_price ?? raw.reference_price ?? NaN),
    route: String(raw.route ?? raw.routing_decision ?? "default"),
  };
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

export const useControlSystemStore = create<ControlSystemState>((set) => ({
  symbol: "BTCUSDT",
  market: initialMarket,
  signal: initialSignal,
  portfolio: initialPortfolio,
  metrics: initialMetrics,
  tradeTape: [],
  signalLifecycle: [],
  executions: [],
  activeExecutions: [],
  health: {
    reconnectCount: 0,
    avgLatencyMs: 0,
    seqGapCount: 0,
    throughputPerSecond: 0,
    channelStatus: {},
  },
  systemReadinessScore: 0,
  riskState: {},
  metaAlpha: {},
  strategies: [],
  engineState: {},
  logs: [],
  setSymbol: (symbol) => set({ symbol: symbol.toUpperCase() }),
  appendLog: (line) =>
    set((state) => ({ logs: [...state.logs, line].slice(-240) })),
  ingestMarket: (payload) =>
    set((state) => {
      const bids = normalizeDepth(payload.bids);
      const asks = normalizeDepth(payload.asks);
      const lastPrice = Number(
        payload.last_price ?? payload.lastPrice ?? state.market.lastPrice,
      );
      const midPrice = Number(
        payload.mid_price ?? payload.midPrice ?? state.market.midPrice,
      );
      const spreadBps = Number(payload.spread_bps ?? state.market.spreadBps);
      const spread = Number(payload.spread ?? state.market.spread);
      const imbalance = Number(
        payload.order_book_imbalance ??
          payload.imbalance ??
          state.market.imbalance,
      );
      const inferredTrades = deriveTradePrints(payload);

      return {
        market: {
          symbol: String(payload.symbol ?? state.symbol),
          lastPrice: Number.isFinite(lastPrice)
            ? lastPrice
            : state.market.lastPrice,
          midPrice: Number.isFinite(midPrice)
            ? midPrice
            : state.market.midPrice,
          spreadBps: Number.isFinite(spreadBps)
            ? spreadBps
            : state.market.spreadBps,
          spread: Number.isFinite(spread) ? spread : state.market.spread,
          imbalance: clamp(
            Number.isFinite(imbalance) ? imbalance : state.market.imbalance,
            -1,
            1,
          ),
          bids,
          asks,
          stale: Boolean(payload.stale),
        },
        tradeTape: [...inferredTrades, ...state.tradeTape].slice(0, 120),
      };
    }),
  ingestSignal: (payload) =>
    set((state) => {
      const direction = String(
        payload.direction ?? "HOLD",
      ).toUpperCase() as SignalState["direction"];
      const alphaScore = Number(
        payload.alpha_score ?? payload.alphaScore ?? state.signal.alphaScore,
      );
      const confidence = Number(payload.confidence ?? state.signal.confidence);
      const lifecycle: SignalLifecycleEntry[] = [
        {
          id: `${Date.now()}-${Math.random()}`,
          stage: "trigger",
          direction,
          ts: String(payload.timestamp ?? new Date().toISOString()),
          score: Number.isFinite(alphaScore) ? alphaScore : 0,
          notes: `Regime ${String(payload.regime ?? payload.market_state ?? "UNKNOWN")}`,
        },
      ];

      return {
        signal: {
          symbol: String(payload.symbol ?? state.symbol),
          direction:
            direction === "BUY" || direction === "SELL" ? direction : "HOLD",
          confidence: Number.isFinite(confidence)
            ? confidence
            : state.signal.confidence,
          probability: Number(payload.probability ?? state.signal.probability),
          alphaScore: Number.isFinite(alphaScore)
            ? alphaScore
            : state.signal.alphaScore,
          regime: String(payload.regime ?? "UNKNOWN"),
          marketState: String(payload.market_state ?? "UNKNOWN"),
          strategy: String(payload.strategy ?? "alpha_model"),
          timestamp: String(payload.timestamp ?? new Date().toISOString()),
        },
        signalLifecycle: [...lifecycle, ...state.signalLifecycle].slice(0, 60),
      };
    }),
  ingestPortfolio: (payload) =>
    set(() => ({
      portfolio: {
        timestamp: String(payload.timestamp ?? new Date().toISOString()),
        cash: Number(payload.cash ?? 0),
        equity: Number(payload.equity ?? payload.current_equity ?? 0),
        unrealizedPnl: Number(payload.unrealized_pnl ?? 0),
        realizedPnl: Number(payload.realized_pnl ?? 0),
        totalReturn: Number(payload.total_return ?? 0),
        positions: (payload.positions as Record<string, unknown>) ?? {},
      },
    })),
  ingestMetrics: (payload) =>
    set(() => ({
      metrics: {
        timestamp: String(payload.timestamp ?? new Date().toISOString()),
        winRate: Number(payload.win_rate ?? 0),
        sharpeRatio: Number(payload.sharpe_ratio ?? 0),
        maxDrawdown: Number(payload.max_drawdown ?? 0),
        totalTrades: Number(payload.total_trades ?? 0),
        profitableTrades: Number(payload.profitable_trades ?? 0),
        avgWin: Number(payload.avg_win ?? 0),
        avgLoss: Number(payload.avg_loss ?? 0),
      },
    })),
  setExecutions: (history, active) =>
    set(() => ({
      executions: history.map((row) => parseExecutionRow(row)).slice(0, 180),
      activeExecutions: active
        .map((row) => parseExecutionRow(row))
        .slice(0, 60),
    })),
  setHealthStatus: (status) =>
    set((state) => {
      const channelStatus = {
        ...state.health.channelStatus,
        [status.channel]: status,
      };

      const all = Object.values(channelStatus);
      const avgLatency = all.length
        ? Math.round(
            all.reduce((sum, row) => sum + row.averageLatencyMs, 0) /
              all.length,
          )
        : 0;
      const reconnectCount = all.reduce(
        (sum, row) => sum + row.reconnectCount,
        0,
      );
      const seqGapCount = all.reduce((sum, row) => sum + row.seqGapCount, 0);
      const throughputPerSecond = all.reduce(
        (sum, row) => sum + row.throughputPerSecond,
        0,
      );

      return {
        health: {
          reconnectCount,
          avgLatencyMs: avgLatency,
          seqGapCount,
          throughputPerSecond,
          channelStatus,
        },
      };
    }),
  setSystemReadinessScore: (score) => set({ systemReadinessScore: score }),
  setRiskState: (riskState) => set({ riskState }),
  setMetaAlpha: (metaAlpha) => set({ metaAlpha }),
  setStrategies: (strategies) => set({ strategies }),
  setEngineState: (engineState) => set({ engineState }),
}));
