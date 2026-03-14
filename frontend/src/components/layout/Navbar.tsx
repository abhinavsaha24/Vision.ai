"use client";

import { useMarketStore } from "@/store/marketStore";
import { useSignalStore } from "@/store/signalStore";
import { Badge } from "@/components/ui/badge";
import { Bell, Search, Activity } from "lucide-react";
import { useEffect } from "react";

export function Navbar() {
  const { livePrice, symbol } = useMarketStore();
  const { riskStatus, fetchRiskStatus } = useSignalStore();

  useEffect(() => {
    fetchRiskStatus();
    const interval = setInterval(() => {
      fetchRiskStatus();
    }, 15000);
    return () => clearInterval(interval);
  }, [symbol, fetchRiskStatus]);

  return (
    <header className="flex h-16 items-center justify-between border-b border-slate-800 bg-slate-950/80 px-6 backdrop-blur-xl">
      <div className="flex items-center gap-4 flex-1">
        <div className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-1.5 focus-within:border-indigo-500/50 focus-within:ring-1 focus-within:ring-indigo-500/50">
          <Search className="h-4 w-4 text-slate-400" />
          <input 
            type="text" 
            placeholder="Search symbols..." 
            className="bg-transparent text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none w-48"
          />
        </div>
      </div>

      <div className="flex items-center gap-6">
        <div className="flex items-center gap-3">
          <span className="text-sm text-slate-400 font-medium">{symbol}</span>
          <span className="text-lg font-bold text-slate-100 font-mono tracking-tight">
            {livePrice ? `$${livePrice.toFixed(2)}` : 'Loading...'}
          </span>
        </div>

        <div className="h-6 w-px bg-slate-800" />

        <div className="flex items-center gap-3">
          <span className="text-sm text-slate-400">System Status</span>
          <Badge variant={riskStatus?.risk_level === 'high' ? 'danger' : 'success'} className="gap-1.5">
            <Activity className="h-3 w-3" />
            {riskStatus?.risk_level === 'high' ? 'High Risk' : 'Healthy'}
          </Badge>
        </div>

        <div className="h-6 w-px bg-slate-800" />

        <button className="relative rounded-full p-2 text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-200">
          <Bell className="h-5 w-5" />
          <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-indigo-500 ring-2 ring-slate-950" />
        </button>
      </div>
    </header>
  );
}
