import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useMarketStore } from "@/store/marketStore";

interface OrderBookRow {
  price: number;
  amount: number;
  total: number;
  depthPercent: number;
}

export function OrderBook() {
  const { symbol, livePrice } = useMarketStore();
  const [bids, setBids] = useState<OrderBookRow[]>([]);
  const [asks, setAsks] = useState<OrderBookRow[]>([]);

  useEffect(() => {
    // Generate deterministic fake order book data spread around livePrice
    // In a real app, this would come securely from Binance WS depth stream.
    const interval = setInterval(() => {
      if (!livePrice) return;
      
      const priceDecimals = livePrice < 1 ? 4 : 2;
      const step = livePrice * 0.0001; // 0.01% spread

      // Generate Asks (sell orders are above current price)
      let currentAskTotal = 0;
      const newAsks: OrderBookRow[] = Array.from({ length: 15 }).map((_, i) => {
        const price = livePrice + (i * step) + step;
        const amount = Math.random() * 2.5 + 0.1;
        currentAskTotal += amount;
        return { price, amount, total: currentAskTotal, depthPercent: 0 };
      }).reverse(); // Reverse so lowest ask is at the bottom of the top half

      // Generate Bids (buy orders are below current price)
      let currentBidTotal = 0;
      const newBids: OrderBookRow[] = Array.from({ length: 15 }).map((_, i) => {
        const price = livePrice - (i * step) - step;
        const amount = Math.random() * 2.5 + 0.1;
        currentBidTotal += amount;
        return { price, amount, total: currentBidTotal, depthPercent: 0 };
      });

      // Calculate depth percentages based on max total volume across the book
      // We use currentAskTotal/currentBidTotal directly because the array accumulations hold the max at their boundaries
      const maxVolume = Math.max(
        currentAskTotal, // The largest total is at the end of the un-reversed asks list, which is newAsks[0].total
        currentBidTotal 
      );

      const calculatedAsks = newAsks.map(a => ({ ...a, depthPercent: Math.min((a.total / maxVolume) * 100, 100) }));
      const calculatedBids = newBids.map(b => ({ ...b, depthPercent: Math.min((b.total / maxVolume) * 100, 100) }));

      setAsks(calculatedAsks);
      setBids(calculatedBids);
    }, 1000); // Update every second to mimic fast order book changes

    return () => clearInterval(interval);
  }, [livePrice, symbol]);

  if (!livePrice) {
    return (
      <Card className="flex flex-col h-full bg-slate-900 border-slate-800">
        <CardContent className="flex flex-col items-center justify-center flex-1 h-[400px]">
          <span className="text-slate-500 font-mono text-sm tracking-widest uppercase">Connecting to L2...</span>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="flex flex-col h-full bg-slate-900 border-slate-800">
      <CardHeader className="py-3 border-b border-slate-800/50">
        <CardTitle className="text-sm font-medium text-slate-200 flex items-center justify-between">
          <span>Order Book</span>
          <span className="text-[10px] bg-slate-800 px-2 py-0.5 rounded text-slate-400 font-mono tracking-widest uppercase">
            {symbol}
          </span>
        </CardTitle>
        <div className="grid grid-cols-3 text-[10px] font-semibold text-slate-500 uppercase tracking-wider mt-2 px-1">
          <div>Price(USDT)</div>
          <div className="text-right">Amount(BTC)</div>
          <div className="text-right">Total</div>
        </div>
      </CardHeader>
      
      <CardContent className="flex-1 p-0 overflow-hidden flex flex-col font-mono text-[11px]">
        {/* Asks (Reds) - Sell Orders at the top */}
        <div className="flex-1 overflow-hidden flex flex-col justify-end">
          {asks.map((ask, i) => (
            <div key={`ask-${i}`} className="relative grid grid-cols-3 py-[2px] px-4 hover:bg-slate-800/50 cursor-pointer group">
              <div 
                className="absolute right-0 top-0 bottom-0 bg-rose-500/10 transition-all duration-300"
                style={{ width: `${ask.depthPercent}%` }}
              />
              <div className="text-rose-400 relative z-10">{ask.price.toFixed(2)}</div>
              <div className="text-slate-300 relative z-10 text-right">{ask.amount.toFixed(3)}</div>
              <div className="text-slate-500 relative z-10 text-right">{ask.total.toFixed(3)}</div>
            </div>
          ))}
        </div>

        {/* Current Price Divider */}
        <div className="py-2 px-4 border-y border-slate-800 flex items-center justify-between bg-slate-950/50">
          <span className="text-lg font-bold text-emerald-400">
            {livePrice.toFixed(2)}
          </span>
          <span className="text-xs text-slate-500 underline decoration-dashed">
            Mark: ${(livePrice + 0.5).toFixed(2)}
          </span>
        </div>

        {/* Bids (Greens) - Buy Orders at the bottom */}
        <div className="flex-1 overflow-hidden flex flex-col">
          {bids.map((bid, i) => (
            <div key={`bid-${i}`} className="relative grid grid-cols-3 py-[2px] px-4 hover:bg-slate-800/50 cursor-pointer group">
              <div 
                className="absolute right-0 top-0 bottom-0 bg-emerald-500/10 transition-all duration-300"
                style={{ width: `${bid.depthPercent}%` }}
              />
              <div className="text-emerald-400 relative z-10">{bid.price.toFixed(2)}</div>
              <div className="text-slate-300 relative z-10 text-right">{bid.amount.toFixed(3)}</div>
              <div className="text-slate-500 relative z-10 text-right">{bid.total.toFixed(3)}</div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
