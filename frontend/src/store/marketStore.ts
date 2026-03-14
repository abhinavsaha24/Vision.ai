import { create } from 'zustand';
import { wsService } from '@/services/websocket';
import { MarketKline } from '@/types';

interface MarketState {
  symbol: string;
  timeframe: string;
  livePrice: number | null;
  liveKline: MarketKline | null;
  historicalData: MarketKline[];
  setSymbol: (symbol: string) => void;
  setTimeframe: (time: string) => void;
  setHistoricalData: (data: MarketKline[]) => void;
  fetchHistoricalData: (symbol: string, timeframe: string) => Promise<void>;
  updateLivePrice: (data: MarketKline) => void;
  startWebSocket: () => void;
  stopWebSocket: () => void;
}

export const useMarketStore = create<MarketState>((set, get) => ({
  symbol: 'BTCUSDT',
  timeframe: '1m',
  livePrice: null,
  liveKline: null,
  historicalData: [],

  setSymbol: (symbol) => {
    set({ symbol });
    const { timeframe } = get();
    get().fetchHistoricalData(symbol, timeframe);
    get().startWebSocket(); 
  },

  setTimeframe: (timeframe) => {
    set({ timeframe });
    const { symbol } = get();
    get().fetchHistoricalData(symbol, timeframe);
    get().startWebSocket(); 
  },

  setHistoricalData: (data) => set({ historicalData: data }),

  fetchHistoricalData: async (symbol, timeframe) => {
    try {
      const formattedSymbol = symbol.toUpperCase();
      const response = await fetch(`https://api.binance.com/api/v3/klines?symbol=${formattedSymbol}&interval=${timeframe}&limit=200`);
      const data = await response.json();
      
      const formattedData: MarketKline[] = data.map((d: any) => ({
        time: Math.floor(d[0] / 1000), // open time in seconds
        open: parseFloat(d[1]),
        high: parseFloat(d[2]),
        low: parseFloat(d[3]),
        close: parseFloat(d[4]),
        volume: parseFloat(d[5]),
      }));
      
      set({ historicalData: formattedData });
    } catch (err) {
      console.error('[MarketStore] Failed to fetch historical data from Binance:', err);
    }
  },

  updateLivePrice: (data) => {
    set({ livePrice: data.close, liveKline: data });
  },

  startWebSocket: () => {
    const { symbol, timeframe, updateLivePrice, historicalData } = get();
    if (historicalData.length === 0) {
      get().fetchHistoricalData(symbol, timeframe);
    }
    wsService.connect(symbol, timeframe);
    wsService.subscribe(updateLivePrice);
  },

  stopWebSocket: () => {
    const { updateLivePrice } = get();
    wsService.unsubscribe(updateLivePrice);
    wsService.disconnect();
  }
}));
