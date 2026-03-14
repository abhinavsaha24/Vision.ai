import React from 'react';
import { Layers, CheckCircle2, XCircle } from 'lucide-react';

export default function StrategyTable({ strategiesData, loading }) {
  if (loading || !strategiesData) {
    return (
      <div className="panel flex flex-col items-center justify-center text-dark-muted h-48">
        <Layers className="w-6 h-6 mb-2 opacity-50" />
        <span className="text-xs font-mono">STRATEGIES UNAVAILABLE</span>
      </div>
    );
  }

  const strategies = strategiesData.strategies || [];
  const activeCount = strategies.filter(s => s.active).length;

  return (
    <div className="panel h-full flex flex-col">
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <h2 className="text-sm font-bold text-dark-muted uppercase tracking-wider flex items-center space-x-2">
          <Layers className="w-4 h-4" />
          <span>Strategy Library</span>
        </h2>
        <span className="text-xs bg-dark-bg px-2 py-1 rounded border border-dark-border text-dark-muted font-mono">
          {activeCount} / {strategies.length} ACTIVE
        </span>
      </div>

      <div className="flex-1 overflow-y-auto custom-scrollbar pr-2">
        <table className="w-full text-left text-sm font-mono relative border-collapse">
          <thead className="text-xs text-dark-muted sticky top-0 bg-dark-panel z-10 shadow-sm">
            <tr>
              <th className="pb-3 border-b border-dark-border font-medium">STRATEGY NAME</th>
              <th className="pb-3 border-b border-dark-border font-medium px-2">WEIGHT</th>
              <th className="pb-3 border-b border-dark-border font-medium text-right">STATUS</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-dark-border/50">
            {strategies.map((strat, i) => (
              <tr key={strat.key || i} className="hover:bg-dark-bg/50 transition-colors group">
                <td className="py-2.5 truncate max-w-[150px] text-dark-text group-hover:text-white transition-colors" title={strat.name}>
                  {strat.name}
                </td>
                <td className="py-2.5 px-2 text-dark-muted">
                  {(strat.weight * 100).toFixed(0)}%
                </td>
                <td className="py-2.5 text-right flex justify-end items-center">
                  {strat.active ? (
                    <div className="flex items-center space-x-1 text-trade-green bg-trade-green/10 px-2 py-0.5 rounded border border-trade-green/20">
                      <CheckCircle2 className="w-3 h-3" />
                      <span className="text-[10px]">ON</span>
                    </div>
                  ) : (
                    <div className="flex items-center space-x-1 text-dark-muted bg-dark-bg px-2 py-0.5 rounded border border-dark-border">
                      <XCircle className="w-3 h-3" />
                      <span className="text-[10px]">OFF</span>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
