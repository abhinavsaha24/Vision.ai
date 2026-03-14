import React from 'react';
import { History, ArrowUpRight, ArrowDownRight, RefreshCcw } from 'lucide-react';

export default function OrderHistory({ historyData, loading }) {
  if (loading && !historyData) {
    return (
      <div className="panel flex flex-col items-center justify-center text-dark-muted h-48">
        <History className="w-6 h-6 mb-2 opacity-50" />
        <span className="text-xs font-mono">LOADING ORDERS...</span>
      </div>
    );
  }

  const orders = historyData?.orders || [];

  return (
    <div className="panel h-full flex flex-col">
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <h2 className="text-sm font-bold text-dark-muted uppercase tracking-wider flex items-center space-x-2">
          <History className="w-4 h-4" />
          <span>Execution Feed</span>
        </h2>
        <span className="text-xs bg-dark-bg px-2 py-1 rounded border border-dark-border text-dark-muted font-mono whitespace-nowrap">
          {historyData?.statistics?.total_orders || 0} TOTAL
        </span>
      </div>

      <div className="flex-1 overflow-y-auto custom-scrollbar pr-2">
        {orders.length === 0 ? (
          <div className="text-xs font-mono text-dark-muted italic p-4 text-center">No trades executed yet</div>
        ) : (
          <table className="w-full text-left text-sm font-mono relative border-collapse">
            <thead className="text-[10px] text-dark-muted sticky top-0 bg-dark-panel z-10 shadow-sm uppercase tracking-wider">
              <tr>
                <th className="pb-2 border-b border-dark-border font-medium">TIME</th>
                <th className="pb-2 border-b border-dark-border font-medium">SYMBOL</th>
                <th className="pb-2 border-b border-dark-border font-medium">SIDE</th>
                <th className="pb-2 border-b border-dark-border font-medium text-right">PRICE</th>
                <th className="pb-2 border-b border-dark-border font-medium text-right">SIZE</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-dark-border/50 text-xs">
              {orders.map((order, i) => {
                const isBuy = order.side === 'BUY';
                const Icon = isBuy ? ArrowUpRight : ArrowDownRight;
                const color = isBuy ? 'text-trade-green' : 'text-trade-red';
                
                return (
                  <tr key={order.id || i} className="hover:bg-dark-bg/50 transition-colors">
                    <td className="py-2 text-dark-muted whitespace-nowrap">
                      {new Date(order.timestamp).toLocaleTimeString('en-US', {hour12: false})}
                    </td>
                    <td className="py-2 text-white">{order.symbol}</td>
                    <td className="py-2">
                      <div className={`flex items-center space-x-1 ${color}`}>
                        <Icon className="w-3 h-3" />
                        <span className="font-bold">{order.side}</span>
                      </div>
                    </td>
                    <td className="py-2 text-right font-bold">
                      ${order.price?.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}
                    </td>
                    <td className="py-2 text-right font-bold">
                      {order.size || order.amount || '-'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
