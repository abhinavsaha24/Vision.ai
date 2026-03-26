export interface MarketKline {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface MarketSnapshot {
  symbol: string;
  exchange: string;
  last_price: number;
  mid_price: number;
  spread: number;
  spread_bps: number;
  order_book_imbalance: number;
  volume_24h: number;
  bids: [number, number][];
  asks: [number, number][];
  stale: boolean;
  age_seconds: number;
  connection_state: string;
}

export interface MetaAlphaResponse {
  signal: string;
  probability: number;
  confidence: number;
  alpha_score: number;
  contributing_signals: Array<{
    name: string;
    raw: number;
    weight: number;
    contribution: number;
  }>;
  market_context: {
    spread_bps: number;
    order_book_imbalance: number;
    stale: boolean;
    connection_state: string;
  };
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
  signal_confidence?: number;
  probability?: number;
  predictions?: PredictionResult[];
  market_snapshot?: MarketSnapshot;
  meta_alpha?: MetaAlphaResponse;
  sentiment?: {
    score: number;
    label: string;
  };
  regime?: string;
  risk_level?: string;
}

export interface PortfolioStatus {
  current_equity: number;
  cash: number;
  positions_value: number;
  unrealized_pnl: number;
  positions: Record<string, unknown>;
}

export interface RiskStatus {
  risk_level: string;
  risk_score: number;
  kill_switch: boolean;
  events: unknown[];
}

export interface NewsArticle {
  title: string;
  url: string;
  source: string;
  published_at: string;
}
