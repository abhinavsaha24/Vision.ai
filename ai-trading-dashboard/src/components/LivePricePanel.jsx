import React, { useState, useEffect, useRef } from 'react';
import { TrendingUp, TrendingDown, RefreshCcw } from 'lucide-react';
import { motion } from 'framer-motion';

export default function LivePricePanel({ symbol }) {
  const [priceData, setPriceData] = useState({
    price: 0,
    change: 0,
    changePercent: 0,
    isUp: true
  });
  
  const [flash, setFlash] = useState(null); // 'up' or 'down'
  const wsRef = useRef(null);
  const prevPriceRef = useRef(0);

  useEffect(() => {
    // Convert BTC/USDT -> btcusdt for Binance streams
    const streamSymbol = symbol.replace('/', '').toLowerCase();
    const wsUrl = `wss://stream.binance.com/ws/${streamSymbol}@ticker`;

    let ws = null;
    let reconnectTimeout = null;

    const connectWS = () => {
      ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        const currentPrice = parseFloat(data.c);
        const prevPrice = prevPriceRef.current;
        
        // Determine flash animation
        if (prevPrice !== 0 && currentPrice !== prevPrice) {
          setFlash(currentPrice > prevPrice ? 'up' : 'down');
          // Clear flash after animation
          setTimeout(() => setFlash(null), 1000);
        }
        
        prevPriceRef.current = currentPrice;

        setPriceData({
          price: currentPrice,
          change: parseFloat(data.p),
          changePercent: parseFloat(data.P),
          isUp: parseFloat(data.P) >= 0
        });
      };

      ws.onerror = (error) => {
        console.error('Binance WS Error:', error);
      };

      ws.onclose = () => {
        console.log('Binance WS Closed. Reconnecting in 3s...');
        reconnectTimeout = setTimeout(connectWS, 3000);
      };
    };

    connectWS();

    return () => {
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      if (ws) {
        ws.onclose = null; // Prevent reconnect loop on unmount
        ws.close();
      }
    };
  }, [symbol]);

  const pColor = priceData.isUp ? 'text-trade-green' : 'text-trade-red';
  const Icon = priceData.isUp ? TrendingUp : TrendingDown;

  return (
    <div className="panel flex flex-col justify-between">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-sm font-bold text-dark-muted uppercase tracking-wider flex items-center space-x-2">
          <RefreshCcw className="w-4 h-4" />
          <span>Live Market data</span>
        </h2>
        <span className="text-xs bg-dark-bg px-2 py-1 rounded border border-dark-border text-dark-muted">BINANCE</span>
      </div>

      <div className="flex items-end justify-between mt-4">
        <div>
          <motion.div
            key={`${symbol}-${priceData.price}`} // force re-render for flash class
            className={`text-4xl font-mono font-bold font-numeric ${flash === 'up' ? 'flash-up' : flash === 'down' ? 'flash-down' : ''}`}
          >
            {priceData.price !== 0 ? priceData.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 }) : '---'}
          </motion.div>
          <div className="text-sm text-dark-muted font-mono mt-1">
            {symbol} Current Price
          </div>
        </div>

        {priceData.price !== 0 && (
          <div className={`flex flex-col items-end ${pColor}`}>
            <div className="flex items-center space-x-1 font-mono font-bold text-lg">
              <Icon className="w-5 h-5" />
              <span>{priceData.changePercent > 0 ? '+' : ''}{priceData.changePercent.toFixed(2)}%</span>
            </div>
            <div className="text-sm font-mono mt-1 opacity-80">
              {priceData.change > 0 ? '+' : ''}{priceData.change.toLocaleString()}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
