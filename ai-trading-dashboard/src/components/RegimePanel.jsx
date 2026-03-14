import React from 'react';
import { Compass, Waves, AlertTriangle } from 'lucide-react';

export default function RegimePanel({ regimeData, loading }) {
  if (loading || !regimeData) {
    return (
      <div className="panel flex flex-col items-center justify-center text-dark-muted h-32">
        <span className="text-xs font-mono">REGIME DATA UNAVAILABLE</span>
      </div>
    );
  }

  const { label, trend, volatility } = regimeData;

  const labelColor = 
    label === 'bullish' ? 'text-trade-green' :
    label === 'bearish' ? 'text-trade-red' : 'text-trade-yellow';

  return (
    <div className="panel h-full flex flex-col justify-between">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-bold text-dark-muted uppercase tracking-wider flex items-center space-x-2">
          <Compass className="w-4 h-4" />
          <span>Market Regime</span>
        </h2>
        <span className="text-xs bg-dark-bg px-2 py-1 rounded border border-dark-border text-dark-muted font-mono">HMM + RULE</span>
      </div>

      <div className="grid grid-cols-3 gap-2 flex-1">
        <div className="bg-dark-bg border border-dark-border rounded-lg p-3 flex flex-col justify-between relative overflow-hidden group hover:border-dark-muted transition-colors">
          <div className="absolute top-0 right-0 p-2 opacity-10 group-hover:opacity-20 transition-opacity">
            <Compass className={`w-8 h-8 ${labelColor}`} />
          </div>
          <div className="text-xs text-dark-muted mb-2 font-mono z-10">STATE</div>
          <div className={`text-lg font-bold uppercase tracking-wider z-10 ${labelColor}`}>
            {label}
          </div>
        </div>

        <div className="bg-dark-bg border border-dark-border rounded-lg p-3 flex flex-col justify-between relative overflow-hidden group hover:border-dark-muted transition-colors">
          <div className="absolute top-0 right-0 p-2 opacity-10 group-hover:opacity-20 transition-opacity">
            <Waves className="w-8 h-8 text-blue-400" />
          </div>
          <div className="text-xs text-dark-muted mb-2 font-mono z-10">TREND</div>
          <div className="text-lg font-bold uppercase tracking-wider text-blue-400 z-10 text-ellipsis overflow-hidden">
            {trend?.replace('_', ' ')}
          </div>
        </div>

        <div className="bg-dark-bg border border-dark-border rounded-lg p-3 flex flex-col justify-between relative overflow-hidden group hover:border-dark-muted transition-colors">
          <div className="absolute top-0 right-0 p-2 opacity-10 group-hover:opacity-20 transition-opacity">
            <AlertTriangle className="w-8 h-8 text-orange-400" />
          </div>
          <div className="text-xs text-dark-muted mb-2 font-mono z-10">VOLATILITY</div>
          <div className="text-lg font-bold uppercase tracking-wider text-orange-400 z-10 text-ellipsis overflow-hidden">
            {volatility?.replace('_', ' ')}
          </div>
        </div>
      </div>
    </div>
  );
}
