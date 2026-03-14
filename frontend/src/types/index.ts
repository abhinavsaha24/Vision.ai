export interface MarketKline {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface PredictionResult {
  step: number;
  direction: string;
  probability: number;
  confidence: number;
  regime: string;
}

export interface PredictionResponse {
  symbol: string;
  signal: string;
  confidence: number;
  probability: number;
  regime: string;
  risk_level: string;
}

export interface PortfolioStatus {
  current_equity: number;
  cash: number;
  positions_value: number;
  unrealized_pnl: number;
  positions: Record<string, any>;
}

export interface RiskStatus {
  risk_level: string;
  risk_score: number;
  kill_switch: boolean;
  events: any[];
}

export interface NewsArticle {
  title: string;
  url: string;
  source: string;
  published_at: string;
}
