"use client";

import { useSignalStore } from "@/store/signalStore";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Wallet, TrendingUp, TrendingDown, Layers } from "lucide-react";
import { PaperTradingControl } from "@/components/portfolio/PaperTradingControl";
import { OrderHistoryTable } from "@/components/portfolio/OrderHistoryTable";
import { DailyPnLCurve } from "@/components/portfolio/DailyPnLCurve";

export default function PortfolioPage() {
  const { portfolioStatus } = useSignalStore();

  const total = portfolioStatus?.current_equity || 0;
  const positionsValue = portfolioStatus?.positions_value || 0;
  const cash = portfolioStatus?.cash || 0;
  const pnl = portfolioStatus?.unrealized_pnl || 0;

  return (
    <div className="flex flex-col gap-6 max-w-6xl mx-auto">
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold tracking-tight text-white">Portfolio</h1>
        <p className="text-slate-400">Total assets, equity curves, and performance tracking.</p>
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-3 text-white">
        <Card className="bg-slate-900 border-slate-800">
          <CardHeader>
            <CardTitle className="text-sm text-slate-400 flex items-center gap-2">
              <Wallet className="h-4 w-4" /> Total Equity
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-4xl font-bold">
              ${total.toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </div>
            <div className="mt-2 flex gap-4 text-sm">
              <div className="flex flex-col">
                <span className="text-slate-500">Cash</span>
                <span className="font-mono">${cash.toLocaleString()}</span>
              </div>
              <div className="flex flex-col">
                <span className="text-slate-500">Positions</span>
                <span className="font-mono">${positionsValue.toLocaleString()}</span>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-slate-900 border-slate-800">
          <CardHeader>
            <CardTitle className="text-sm text-slate-400 flex items-center gap-2">
              Unrealized PnL
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className={`text-4xl font-bold flex items-center gap-3 ${pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {pnl >= 0 ? <TrendingUp className="h-8 w-8" /> : <TrendingDown className="h-8 w-8" />}
              {pnl > 0 ? '+' : ''}${pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 text-white h-[800px] mb-8">
        <div className="lg:col-span-1 flex flex-col gap-6">
          <PaperTradingControl />
          
          <Card className="bg-slate-900 border-slate-800 flex-1 flex flex-col min-h-0">
            <CardHeader className="pb-3 border-b border-slate-800/50">
              <CardTitle className="text-sm text-slate-400 flex items-center gap-2">
                <Layers className="h-4 w-4" /> Active Positions
              </CardTitle>
            </CardHeader>
            <CardContent className="flex-1 overflow-y-auto p-4">
              {portfolioStatus?.positions && Object.keys(portfolioStatus.positions).length > 0 ? (
                 <div className="text-slate-300">Positions active.</div>
              ) : (
                <div className="py-12 text-center text-slate-500 text-xs font-mono">
                  No active positions.
                </div>
              )}
            </CardContent>
          </Card>

          <div className="flex-1 min-h-[300px] max-h-[400px]">
             <DailyPnLCurve />
          </div>
        </div>

        <div className="lg:col-span-2">
          <OrderHistoryTable />
        </div>
      </div>
    </div>
  );
}
