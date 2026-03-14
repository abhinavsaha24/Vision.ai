import axios from 'axios';
import { PredictionResponse, PortfolioStatus, RiskStatus, NewsArticle } from '@/types';

// The backend might be running locally or on Render
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:10000';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error(`[VISION AI API ERROR]`, error?.response?.data || error.message);
    return Promise.reject(error);
  }
);

export const apiService = {
  async getHealth(): Promise<any> {
    const { data } = await apiClient.get(`/health`);
    return data;
  },

  async getPrediction(symbol: string = 'BTCUSDT', horizon: number = 5): Promise<PredictionResponse> {
    const { data } = await apiClient.post<PredictionResponse>(`/model/predict`, { symbol, horizon });
    return data;
  },

  async getPortfolioPerformance(): Promise<any> {
    const { data } = await apiClient.get<any>(`/portfolio/performance`);
    return data;
  },

  async getRiskStatus(): Promise<RiskStatus> {
    const { data } = await apiClient.get<RiskStatus>(`/risk/status`);
    return data;
  },

  async getStrategies(): Promise<any> {
    const { data } = await apiClient.get<any>(`/strategies/list`);
    return data;
  },

  async getRegime(): Promise<any> {
    const { data } = await apiClient.get<any>(`/regime/current`);
    return data;
  },

  async getSentiment(): Promise<any> {
    const { data } = await apiClient.get<any>(`/sentiment/current`);
    return data;
  },

  async getNews(limit: number = 10): Promise<{ articles: NewsArticle[]; count: number }> {
    const { data } = await apiClient.get(`/news`, { params: { limit } });
    return data;
  },

  async getOrderHistory(): Promise<any> {
    const { data } = await apiClient.get<any>(`/orders/history`);
    return data;
  },

  async getPaperStatus(): Promise<any> {
    const { data } = await apiClient.get<any>(`/paper-trading/status`);
    return data;
  },

  async startPaperTrading(symbol: string, initial_cash: number = 10000, interval_seconds: number = 300): Promise<any> {
    const { data } = await apiClient.post<any>(`/paper-trading/start`, { symbol, initial_cash, interval_seconds });
    return data;
  }
};
