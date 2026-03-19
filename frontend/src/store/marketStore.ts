"use client";

import { create } from "zustand";

export interface MarketSnapshot {
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
  timestamp?: string;
}

export interface SignalSnapshot {
  symbol: string;
  timestamp: string;
  direction: "BUY" | "SELL" | "HOLD";
  confidence: number;
  probability: number;
  alpha_score: number;
  regime: string;
  market_state: string;
  strategy: string;
}

interface MarketState {
  symbol: string;
  market: MarketSnapshot | null;
  signal: SignalSnapshot | null;
  setSymbol: (symbol: string) => void;
  updateMarket: (snapshot: MarketSnapshot) => void;
  updateSignal: (snapshot: SignalSnapshot) => void;
}

export const useMarketStore = create<MarketState>((set) => ({
  symbol: "BTCUSDT",
  market: null,
  signal: null,
  setSymbol: (symbol) => set({ symbol: symbol.toUpperCase() }),
  updateMarket: (market) => set({ market }),
  updateSignal: (signal) => set({ signal }),
}));
