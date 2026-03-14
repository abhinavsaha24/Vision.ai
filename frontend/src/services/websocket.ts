import { MarketKline } from '@/types';

export type WebSocketCallback = (data: MarketKline) => void;

class BinanceWebSocketService {
  private ws: WebSocket | null = null;
  private subscribers: Set<WebSocketCallback> = new Set();
  private symbol: string = 'btcusdt';
  private timeframe: string = '1m';


  connect(symbol: string = 'btcusdt', timeframe: string = '1m') {
    if (this.ws && this.symbol === symbol && this.timeframe === timeframe) {
      return; // Already connected to this stream
    }

    this.symbol = symbol.toLowerCase();
    this.timeframe = timeframe;

    if (this.ws) {
      this.ws.close();
    }

    const wsUrl = `wss://stream.binance.com:9443/ws/${this.symbol}@kline_${this.timeframe}`;
    console.log(`[WebSocket] Connecting to ${wsUrl}`);
    
    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      console.log('[WebSocket] Connected');
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.e === 'kline' && msg.k) {
          const kline = msg.k;
          const klineData: MarketKline = {
            time: Math.floor(kline.t / 1000), // convert to seconds for lightweight-charts
            open: parseFloat(kline.o),
            high: parseFloat(kline.h),
            low: parseFloat(kline.l),
            close: parseFloat(kline.c),
            volume: parseFloat(kline.v),
          };
          this.notifySubscribers(klineData);
        }
      } catch (e) {
        console.error('[WebSocket] Message parsing error:', e);
      }
    };

    this.ws.onerror = (error) => {
      console.error('[WebSocket] Error:', error);
    };

    this.ws.onclose = () => {
      console.log('[WebSocket] Disconnected');
      this.attemptReconnect();
    };
  }

  private attemptReconnect() {
    console.log(`[WebSocket] Reconnecting in 2000ms...`);
    setTimeout(() => {
      this.connect(this.symbol, this.timeframe);
    }, 2000);
  }

  subscribe(callback: WebSocketCallback) {
    this.subscribers.add(callback);
    return () => this.unsubscribe(callback);
  }

  unsubscribe(callback: WebSocketCallback) {
    this.subscribers.delete(callback);
  }

  private notifySubscribers(data: MarketKline) {
    this.subscribers.forEach(callback => callback(data));
  }

  disconnect() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.subscribers.clear();
  }
}

export const wsService = new BinanceWebSocketService();
