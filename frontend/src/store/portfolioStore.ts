"use client";

import { create } from "zustand";

export interface Position {
  symbol: string;
  side: "long" | "short";
  quantity: number;
  entry_price: number;
  current_price: number;
  unrealized_pnl: number;
}

export interface PortfolioSnapshot {
  timestamp: string;
  cash: number;
  equity: number;
  unrealized_pnl: number;
  realized_pnl: number;
  total_return: number;
  positions: Record<string, Position>;
}

export interface MetricsSnapshot {
  timestamp: string;
  win_rate: number;
  sharpe_ratio: number;
  max_drawdown: number;
  total_trades: number;
  profitable_trades: number;
  avg_win: number;
  avg_loss: number;
}

interface PortfolioState {
  portfolio: PortfolioSnapshot | null;
  metrics: MetricsSnapshot | null;
  equityHistory: Array<{ time: string; equity: number }>;
  updatePortfolio: (snapshot: PortfolioSnapshot) => void;
  updateMetrics: (snapshot: MetricsSnapshot) => void;
}

export const usePortfolioStore = create<PortfolioState>((set) => ({
  portfolio: null,
  metrics: null,
  equityHistory: [],
  updatePortfolio: (portfolio) =>
    set((state) => {
      const time = portfolio.timestamp || new Date().toISOString();
      const point = {
        time,
        equity: Number(portfolio.equity || 0),
      };
      const history = [...state.equityHistory, point].slice(-240);
      return { portfolio, equityHistory: history };
    }),
  updateMetrics: (metrics) => set({ metrics }),
}));
