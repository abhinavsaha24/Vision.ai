import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { History, ArrowUpRight, ArrowDownRight, Clock } from "lucide-react";
import { apiService } from "@/services/api";

interface Order {
  id?: string;
  timestamp: string;
  symbol: string;
  side: "BUY" | "SELL";
  price: number;
  size: number;
  amount?: number;
}

export function OrderHistoryTable() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<{ total_orders: number }>({ total_orders: 0 });

  useEffect(() => {
    let mounted = true;
    async function fetchHistory() {
      try {
        const data = await apiService.getOrderHistory();
        if (mounted) {
          setOrders(data?.orders || []);
          setStats(data?.statistics || { total_orders: 0 });
          setLoading(false);
        }
      } catch (err) {
        if (mounted) setLoading(false);
      }
    }
    fetchHistory();
    const interval = setInterval(fetchHistory, 15000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  return (
    <Card className="flex flex-col h-full bg-slate-900 border-slate-800">
      <CardHeader className="pb-3 border-b border-slate-800/50 flex flex-row items-center justify-between">
        <div>
          <CardTitle className="text-lg text-slate-200 flex items-center gap-2">
            <History className="h-5 w-5 text-indigo-400" />
            Execution Feed
          </CardTitle>
          <CardDescription className="text-xs mt-1 text-slate-400">
            Recent algorithmic trades
          </CardDescription>
        </div>
        <div className="bg-slate-800 text-slate-300 px-2.5 py-1 rounded border border-slate-700 text-[10px] font-mono tracking-widest uppercase">
          {stats.total_orders || orders.length} Total
        </div>
      </CardHeader>
      
      <CardContent className="flex-1 p-0 overflow-hidden">
        <div className="h-full overflow-y-auto custom-scrollbar p-0">
          <table className="w-full text-left border-collapse">
            <thead className="text-[10px] text-slate-500 sticky top-0 bg-slate-900 shadow-sm shadow-slate-900 uppercase tracking-wider font-semibold z-10">
              <tr>
                <th className="py-3 px-4 border-b border-slate-800/50">Time</th>
                <th className="py-3 px-4 border-b border-slate-800/50">Symbol</th>
                <th className="py-3 px-4 border-b border-slate-800/50">Action</th>
                <th className="py-3 px-4 border-b border-slate-800/50 text-right">Price</th>
                <th className="py-3 px-4 border-b border-slate-800/50 text-right">Size</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/50 text-sm">
              {loading && orders.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-12 text-center text-slate-500">
                    <div className="flex flex-col items-center gap-2">
                      <Clock className="h-5 w-5 animate-pulse opacity-50" />
                      <span className="text-xs font-mono uppercase tracking-widest">Loading orders...</span>
                    </div>
                  </td>
                </tr>
              ) : orders.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-12 text-center text-slate-500 text-xs font-mono italic">
                    No trades executed yet.
                  </td>
                </tr>
              ) : (
                orders.map((order, i) => {
                  const isBuy = order.side === "BUY";
                  const Icon = isBuy ? ArrowUpRight : ArrowDownRight;
                  const colorClass = isBuy ? "text-emerald-400" : "text-rose-400";
                  const bgClass = isBuy ? "bg-emerald-500/10 border-emerald-500/20" : "bg-rose-500/10 border-rose-500/20";

                  return (
                    <tr key={order.id || i} className="hover:bg-slate-800/30 transition-colors group">
                      <td className="py-3 px-4 text-slate-400 font-mono text-xs whitespace-nowrap">
                        {new Date(order.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}
                      </td>
                      <td className="py-3 px-4 text-slate-200 font-semibold tracking-wider">
                        {order.symbol}
                      </td>
                      <td className="py-3 px-4">
                        <div className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-[10px] font-bold uppercase tracking-wider ${colorClass} ${bgClass}`}>
                          <Icon className="h-3 w-3" />
                          {order.side}
                        </div>
                      </td>
                      <td className="py-3 px-4 text-right font-mono text-slate-200">
                        ${order.price?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </td>
                      <td className="py-3 px-4 text-right font-mono font-medium text-slate-300">
                        {order.size || order.amount || "-"}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
