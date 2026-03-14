import { useEffect, useRef, useState } from 'react';
import { createChart } from 'lightweight-charts';
import { LineChart, ZoomIn, ZoomOut, MoveRight, MoveLeft } from 'lucide-react';
import axios from 'axios';

export default function TradingChart({ symbol, signalData }) {
  const chartContainerRef = useRef();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    // Dark theme Chart Config
    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: 'solid', color: 'transparent' },
        textColor: '#94A3B8',
        fontFamily: "'JetBrains Mono', monospace",
      },
      grid: {
        vertLines: { color: 'rgba(51, 65, 85, 0.4)', style: 1 }, // dotted
        horzLines: { color: 'rgba(51, 65, 85, 0.4)', style: 1 },
      },
      crosshair: {
        mode: 0,
        vertLine: { width: 1, color: '#94A3B8', style: 1 },
        horzLine: { width: 1, color: '#94A3B8', style: 1 },
      },
      timeScale: {
        borderColor: '#334155',
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderColor: '#334155',
        autoScale: true,
      },
    });

    const candlestickSeries = chart.addCandlestickSeries({
      upColor: '#10B981',
      downColor: '#EF4444',
      borderVisible: false,
      wickUpColor: '#10B981',
      wickDownColor: '#EF4444',
    });

    // Fetch historical data from Binance API directly (public, no key needed)
    const fetchHistoricalData = async () => {
      try {
        setLoading(true);
        const binanceSymbol = symbol.replace('/', '').toUpperCase();
        // Fetch 500 1-hour candles
        const res = await axios.get(`https://api.binance.com/api/v3/klines?symbol=${binanceSymbol}&interval=1h&limit=500`);
        
        const data = res.data.map(d => ({
          time: d[0] / 1000, // Unix timestamp in seconds
          open: parseFloat(d[1]),
          high: parseFloat(d[2]),
          low: parseFloat(d[3]),
          close: parseFloat(d[4]),
        }));

        candlestickSeries.setData(data);

        // Add Prediction Marker if available
        if (signalData && signalData.signal && (signalData.signal === 'BUY' || signalData.signal === 'SELL')) {
          const lastTime = data[data.length - 1].time;
          const isBuy = signalData.signal === 'BUY';
          candlestickSeries.setMarkers([
            {
              time: lastTime,
              position: isBuy ? 'belowBar' : 'aboveBar',
              color: isBuy ? '#22c55e' : '#ef4444',
              shape: isBuy ? 'arrowUp' : 'arrowDown',
              text: signalData.signal,
              size: 2,
            }
          ]);
        }

        setLoading(false);
      } catch (err) {
        console.error("Failed to load chart data:", err);
        setLoading(false);
      }
    };

    fetchHistoricalData();

    // Attach chart reference to the window for button controls
    window.tvChart = chart;
    window.tvSeries = candlestickSeries;

    // Resize observer to keep chart responsive
    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [symbol, signalData]);

  return (
    <div className="panel h-[460px] w-full flex flex-col relative">
      <div className="flex items-center justify-between mb-2">
         <h2 className="text-sm font-bold text-dark-muted uppercase tracking-wider flex items-center space-x-2">
          <LineChart className="w-4 h-4" />
          <span>Advanced Chart</span>
        </h2>
        <div className="flex space-x-2 items-center">
            {/* Chart Controls */}
            <div className="flex items-center space-x-1 bg-slate-800 rounded p-1 mr-2">
               <button onClick={() => window.tvChart?.timeScale().scrollToRealTime()} className="p-1 hover:bg-slate-700 rounded text-slate-400 hover:text-white transition-colors"><MoveRight className="w-3 h-3" /></button>
               <button onClick={() => window.tvChart?.timeScale().scrollToPosition(-10, true)} className="p-1 hover:bg-slate-700 rounded text-slate-400 hover:text-white transition-colors"><MoveLeft className="w-3 h-3" /></button>
            </div>
            <span className="text-xs bg-slate-800 px-2 py-1 rounded border border-slate-700 text-slate-300 font-mono">{symbol}</span>
            <span className="text-xs bg-slate-800 px-2 py-1 rounded border border-slate-700 text-slate-300 font-mono">1H</span>
        </div>
      </div>
      
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center z-10 bg-dark-panel/50 backdrop-blur-[2px]">
          <div className="text-xs font-mono text-dark-muted animate-pulse">LOADING CHART DATA...</div>
        </div>
      )}

      {/* Chart container handles its own sizing */}
      <div ref={chartContainerRef} className="flex-1 w-full relative" />
    </div>
  );
}
