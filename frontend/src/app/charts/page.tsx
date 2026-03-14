"use client";

import { useMarketStore } from "@/store/marketStore";
import { TVChart } from "@/components/charts/TVChart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Activity } from "lucide-react";

export default function ChartsPage() {
  const { symbol, timeframe, setTimeframe } = useMarketStore();

  const timeframes = ['1m', '5m', '15m', '1h', '4h', '1d'];

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)] gap-4">
      <div className="flex items-center justify-between">
        <div className="flex flex-col">
          <h1 className="text-3xl font-bold tracking-tight text-white">Advanced Charts</h1>
          <p className="text-slate-400">High-performance TradingView integration for {symbol}</p>
        </div>
        
        <div className="flex items-center gap-2 bg-slate-900/50 p-1 rounded-lg border border-slate-800">
          {timeframes.map((tf) => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                timeframe === tf 
                  ? 'bg-indigo-500 text-white' 
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 w-full relative">
        <TVChart />
      </div>
    </div>
  );
}
