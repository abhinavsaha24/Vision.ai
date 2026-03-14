import React, { useState, useEffect } from 'react';
import { Clock, Server, ShieldPlus, ChevronDown, Activity } from 'lucide-react';

export default function Header({ apiHealth, market, setMarket, onOpenAnalytics }) {
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const pingColor = 
    apiHealth?.latency === undefined ? 'bg-dark-muted' :
    apiHealth.latency < 100 ? 'bg-trade-green' :
    apiHealth.latency < 500 ? 'bg-trade-yellow' : 'bg-trade-red';

  const formatTime = (date) => {
    return date.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }) + ' UTC';
  };

  const isConnected = apiHealth && apiHealth.status !== 'error';

  return (
    <header className="glass-panel flex-shrink-0 flex items-center justify-between mb-4 mt-2 mx-4">
      {/* Brand & Market Selector */}
      <div className="flex items-center space-x-6">
        <div className="flex items-center space-x-2">
          <ShieldPlus className="w-8 h-8 text-trade-green" />
          <div>
            <h1 className="text-xl font-bold tracking-wider leading-none">VISION<span className="text-trade-green">AI</span></h1>
            <span className="text-xs text-dark-muted font-mono tracking-widest uppercase">Quant Terminal</span>
          </div>
        </div>

        <div className="h-8 w-px bg-dark-border" />

        <div className="relative group">
          <button className="flex items-center space-x-2 bg-dark-bg hover:bg-dark-bg/80 border border-dark-border px-4 py-2 rounded-lg transition-colors font-mono font-bold text-lg">
            <span>{market}</span>
            <ChevronDown className="w-4 h-4 text-dark-muted group-hover:text-white transition-colors" />
          </button>
          
          <div className="absolute top-full left-0 mt-2 w-48 bg-dark-bg border border-dark-border rounded-lg shadow-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 z-50">
            {['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT'].map(sym => (
              <button
                key={sym}
                onClick={() => setMarket(sym)}
                className={`w-full text-left px-4 py-2 font-mono hover:bg-dark-panel transition-colors first:rounded-t-lg last:rounded-b-lg ${market === sym ? 'text-trade-green bg-dark-panel/50' : 'text-dark-text'}`}
              >
                {sym}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Clock & Status & Settings */}
      <div className="flex items-center space-x-4 font-mono text-sm">
        
        <button 
          onClick={onOpenAnalytics}
          className="flex items-center space-x-2 bg-dark-bg hover:bg-slate-800 text-slate-300 hover:text-white px-3 py-1.5 rounded-lg border border-dark-border transition-colors group"
          title="Advanced Analytics & Diagnostics"
        >
          <Activity className="w-4 h-4 text-trade-green group-hover:scale-110 transition-transform" />
          <span className="hidden sm:inline">Diagnostics</span>
        </button>

        <div className="flex items-center space-x-2 text-dark-muted bg-dark-bg px-3 py-1.5 rounded-lg border border-dark-border">
          <Clock className="w-4 h-4" />
          <span>{formatTime(time)}</span>
        </div>

        <div className="flex items-center space-x-3 bg-dark-bg px-3 py-1.5 rounded-lg border border-dark-border">
          <div className="flex items-center space-x-2 text-dark-muted">
            <Server className="w-4 h-4" />
            <span>API:</span>
            <span className={isConnected ? 'text-trade-green' : 'text-trade-red'}>
              {isConnected ? 'CONNECTED' : 'DISCONNECTED'}
            </span>
          </div>
          <div className="h-4 w-px bg-dark-border" />
          <div className="flex items-center space-x-2" title={apiHealth?.latency ? `${apiHealth.latency}ms` : 'Unknown'}>
            <div className={`w-2 h-2 rounded-full shadow-[0_0_8px_currentColor] ${pingColor} ${isConnected ? 'animate-pulse' : ''}`} />
            {apiHealth?.latency !== undefined && <span className="text-dark-muted text-xs">{apiHealth.latency}ms</span>}
          </div>
        </div>
      </div>
    </header>
  );
}
