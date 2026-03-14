import React, { useState } from 'react';
import { Play, Square, RefreshCw, Layers } from 'lucide-react';
import { useApi } from '../hooks/useApi';

export default function PaperTradingPanel({ statusData, loading, onRefresh }) {
  const { post, loading: apiLoading } = useApi();
  const [targetSymbol, setTargetSymbol] = useState('BTC/USDT');
  const [cash, setCash] = useState(100000);

  if (loading && !statusData) {
    return (
      <div className="panel flex flex-col items-center justify-center text-dark-muted h-48">
        <RefreshCw className="w-6 h-6 mb-2 animate-spin opacity-50" />
        <span className="text-xs font-mono">LOADING ENGINE...</span>
      </div>
    );
  }

  const isRunning = statusData?.running;
  const isPending = apiLoading['post-/paper-trading/start'] || apiLoading['post-/paper-trading/stop'];

  const handleStart = async () => {
    try {
      await post('/paper-trading/start', {
        symbol: targetSymbol,
        initial_cash: cash,
        interval_seconds: 300 // 5m candle updates
      });
      onRefresh(); // trigger parent to fetch status
    } catch(e) {}
  };

  const handleStop = async () => {
    try {
      await post('/paper-trading/stop');
      onRefresh();
    } catch(e) {}
  };

  return (
    <div className="panel h-full flex flex-col justify-between relative overflow-hidden">
      {/* Background glow when active */}
      {isRunning && (
        <div className="absolute inset-0 bg-trade-green/5 pointer-events-none animate-pulse" />
      )}

      <div className="flex items-center justify-between mb-4 z-10">
        <h2 className="text-sm font-bold text-dark-muted uppercase tracking-wider flex items-center space-x-2">
          <Layers className="w-4 h-4" />
          <span>Paper Trading Engine</span>
        </h2>
        {isRunning ? (
          <span className="text-xs bg-trade-green/20 text-trade-green border border-trade-green/30 px-2 py-1 rounded font-mono animate-pulse">ACTIVE</span>
        ) : (
          <span className="text-xs bg-dark-bg text-dark-muted border border-dark-border px-2 py-1 rounded font-mono">STOPPED</span>
        )}
      </div>

      <div className="flex-1 flex flex-col justify-center space-y-4 z-10">
        
        {/* Controls */}
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <div className="flex-1">
            <label className="text-xs text-dark-muted font-mono mb-1 block">TARGET MAKET</label>
            <select 
              disabled={isRunning}
              value={targetSymbol}
              onChange={e => setTargetSymbol(e.target.value)}
              className="w-full bg-dark-bg border border-dark-border text-white font-mono rounded-lg px-3 py-2 outline-none focus:border-dark-muted disabled:opacity-50"
            >
              <option value="BTC/USDT">BTC/USDT</option>
              <option value="ETH/USDT">ETH/USDT</option>
              <option value="SOL/USDT">SOL/USDT</option>
            </select>
          </div>

          <div className="flex-1">
            <label className="text-xs text-dark-muted font-mono mb-1 block">PAPER CASH ($)</label>
            <input 
              type="number" 
              disabled={isRunning}
              value={cash}
              onChange={e => setCash(Number(e.target.value))}
              className="w-full bg-dark-bg border border-dark-border text-white font-mono rounded-lg px-3 py-2 outline-none focus:border-dark-muted disabled:opacity-50"
            />
          </div>
        </div>

        {/* Status / Buttons */}
        <div className="bg-dark-bg rounded-lg border border-dark-border p-4 flex items-center justify-between">
          <div>
            <div className="text-xs text-dark-muted font-mono uppercase mb-1">CYCLES RUN</div>
            <div className="text-2xl font-mono font-bold">{statusData?.cycle_count || 0}</div>
          </div>

          <div>
            {isRunning ? (
              <button 
                onClick={handleStop}
                disabled={isPending}
                className="flex items-center space-x-2 bg-trade-red/10 text-trade-red border border-trade-red/30 hover:bg-trade-red/20 px-6 py-3 rounded-lg font-bold font-mono transition-colors disabled:opacity-50"
              >
                {isPending ? <RefreshCw className="w-5 h-5 animate-spin" /> : <Square className="w-5 h-5" />}
                <span>STOP ENGINE</span>
              </button>
            ) : (
              <button 
                onClick={handleStart}
                disabled={isPending}
                className="flex items-center space-x-2 bg-trade-green/10 text-trade-green border border-trade-green/30 hover:bg-trade-green/20 hover:shadow-[0_0_16px_rgba(16,185,129,0.3)] px-6 py-3 rounded-lg font-bold font-mono transition-all disabled:opacity-50"
              >
                {isPending ? <RefreshCw className="w-5 h-5 animate-spin" /> : <Play className="w-5 h-5" />}
                <span>START CONTINUOUS</span>
              </button>
            )}
          </div>
        </div>
        
      </div>
    </div>
  );
}
