import { create } from 'zustand';
import { wsService } from '@/services/websocket';
import { MarketKline } from '@/types';

interface MarketState {
  symbol: string;
  timeframe: string;
  livePrice: number | null;
  historicalData: MarketKline[];
  setSymbol: (symbol: string) => void;
  setTimeframe: (time: string) => void;
  setHistoricalData: (data: MarketKline[]) => void;
  updateLivePrice: (data: MarketKline) => void;
  startWebSocket: () => void;
  stopWebSocket: () => void;
}

export const useMarketStore = create<MarketState>((set, get) => ({
  symbol: 'BTCUSDT',
  timeframe: '1m',
  livePrice: null,
  historicalData: [],

  setSymbol: (symbol) => {
    set({ symbol });
    get().startWebSocket(); // Restart WS on symbol change
  },

  setTimeframe: (timeframe) => {
    set({ timeframe });
    get().startWebSocket(); // Restart WS on timeframe change
  },

  setHistoricalData: (data) => set({ historicalData: data }),

  updateLivePrice: (data) => {
    set({ livePrice: data.close });
  },

  startWebSocket: () => {
    const { symbol, timeframe, updateLivePrice } = get();
    wsService.connect(symbol, timeframe);
    wsService.subscribe(updateLivePrice);
  },

  stopWebSocket: () => {
    const { updateLivePrice } = get();
    wsService.unsubscribe(updateLivePrice);
    wsService.disconnect();
  }
}));
