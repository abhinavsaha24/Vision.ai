import { create } from 'zustand';
import { PredictionResponse, RiskStatus, PortfolioStatus } from '@/types';
import { apiService } from '@/services/api';

interface SignalState {
  prediction: PredictionResponse | null;
  riskStatus: RiskStatus | null;
  portfolioStatus: PortfolioStatus | null;
  isLoading: boolean;
  error: string | null;
  
  fetchPrediction: (symbol: string, horizon: number) => Promise<void>;
  fetchRiskStatus: () => Promise<void>;
  fetchPortfolioStatus: () => Promise<void>;
}

export const useSignalStore = create<SignalState>((set) => ({
  prediction: null,
  riskStatus: null,
  portfolioStatus: null,
  isLoading: false,
  error: null,

  fetchPrediction: async (symbol, horizon) => {
    set({ isLoading: true, error: null });
    try {
      const data = await apiService.getPrediction(symbol, horizon);
      set({ prediction: data, isLoading: false });
    } catch (err: any) {
      set({ error: err.message || 'Failed to fetch predictions', isLoading: false });
    }
  },

  fetchRiskStatus: async () => {
    try {
      const data = await apiService.getRiskStatus();
      set({ riskStatus: data });
    } catch (err: any) {
      console.error('Failed to fetch risk status:', err);
    }
  },

  fetchPortfolioStatus: async () => {
    try {
      const data = await apiService.getPortfolioPerformance();
      set({ portfolioStatus: data });
    } catch (err: any) {
      console.error('Failed to fetch portfolio status:', err);
    }
  }
}));
