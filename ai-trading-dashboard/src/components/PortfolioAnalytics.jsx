import React from 'react';
import { PieChart, TrendingUp, DollarSign, Target, Activity } from 'lucide-react';

export default function PortfolioAnalytics({ portfolioData, loading }) {
  if (loading || !portfolioData) {
    return (
      <div className="panel flex flex-col items-center justify-center text-dark-muted h-48">
        <PieChart className="w-6 h-6 mb-2 opacity-50" />
        <span className="text-xs font-mono">PORTFOLIO DATA UNAVAILABLE</span>
      </div>
    );
  }

  const { total_return, win_rate, max_drawdown, total_trades, current_value } = portfolioData;

  const returnColor = total_return >= 0 ? 'text-trade-green' : 'text-trade-red';
  const returnPrefix = total_return >= 0 ? '+' : '';

  return (
    <div className="panel h-full flex flex-col justify-between">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-bold text-dark-muted uppercase tracking-wider flex items-center space-x-2">
          <PieChart className="w-4 h-4" />
          <span>Portfolio Analytics</span>
        </h2>
        <span className="text-xs bg-dark-bg px-2 py-1 rounded border border-dark-border text-dark-muted font-mono">LIVE / PAPER</span>
      </div>

      <div className="grid grid-cols-2 gap-4 flex-1">
        
        {/* Total Return */}
        <div className="bg-dark-bg border border-dark-border rounded-lg p-3 flex flex-col justify-between group hover:border-dark-muted transition-colors">
          <div className="flex items-center space-x-2 text-xs text-dark-muted font-mono mb-2">
            <TrendingUp className="w-4 h-4" />
            <span>TOTAL RETURN</span>
          </div>
          <div className={`text-2xl font-bold font-mono tracking-wider ${returnColor}`}>
            {returnPrefix}{(total_return * 100).toFixed(2)}%
          </div>
        </div>

        {/* Win Rate */}
        <div className="bg-dark-bg border border-dark-border rounded-lg p-3 flex flex-col justify-between group hover:border-dark-muted transition-colors">
          <div className="flex items-center space-x-2 text-xs text-dark-muted font-mono mb-2">
            <Target className="w-4 h-4" />
            <span>WIN RATE</span>
          </div>
          <div className="text-2xl font-bold font-mono tracking-wider text-white">
            {(win_rate * 100).toFixed(1)}%
          </div>
        </div>

        {/* Max Drawdown */}
        <div className="bg-dark-bg border border-dark-border rounded-lg p-3 flex flex-col justify-between group hover:border-dark-muted transition-colors">
          <div className="flex items-center space-x-2 text-xs text-dark-muted font-mono mb-2">
            <Activity className="w-4 h-4" />
            <span>MAX DRAWDOWN</span>
          </div>
          <div className="text-2xl font-bold font-mono tracking-wider text-trade-red">
            {(max_drawdown * 100).toFixed(2)}%
          </div>
        </div>

        {/* Total Trades & Value */}
        <div className="bg-dark-bg border border-dark-border rounded-lg p-3 flex flex-col justify-between group hover:border-dark-muted transition-colors">
           <div className="flex items-center space-x-2 text-xs text-dark-muted font-mono mb-2">
            <DollarSign className="w-4 h-4" />
            <span>VALUE / TRADES</span>
          </div>
          <div className="flex justify-between items-end">
            <div className="text-lg font-bold font-mono tracking-wider text-white">
              ${(current_value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </div>
            <div className="text-sm font-mono text-dark-muted">
              {total_trades}T
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
