"use client";

import { useEffect } from "react";
import { useSignalStore } from "@/store/signalStore";
import { useMarketStore } from "@/store/marketStore";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TVChart } from "@/components/charts/TVChart";
import { StrategyTable } from "@/components/dashboard/StrategyTable";
import { NewsFeed } from "@/components/dashboard/NewsFeed";
import { OrderBook } from "@/components/dashboard/OrderBook";
import { Activity, BrainCircuit, Wallet, TrendingUp, AlertTriangle } from "lucide-react";

export default function DashboardPage() {
  const { symbol, livePrice } = useMarketStore();
  const { 
    prediction, 
    riskStatus, 
    portfolioStatus, 
    fetchPrediction, 
    fetchPortfolioStatus 
  } = useSignalStore();

  useEffect(() => {
    fetchPrediction(symbol, 5);
    fetchPortfolioStatus();
    
    // Polling every 15s
    const interval = setInterval(() => {
      fetchPrediction(symbol, 5);
      fetchPortfolioStatus();
    }, 15000);
    
    return () => clearInterval(interval);
  }, [symbol, fetchPrediction, fetchPortfolioStatus]);

  const pnlPercent = portfolioStatus 
    ? (portfolioStatus.current_equity - 100000) / 100000 * 100 // assuming 100k initial from backend
    : 0;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold tracking-tight text-white">Dashboard</h1>
        <p className="text-slate-400">System overview and AI market intelligence.</p>
      </div>

      {/* Top Stats Row */}
      <div className="grid grid-cols-12 gap-4">
        <Card className="col-span-12 md:col-span-6 lg:col-span-3">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-slate-400">AI Signal</CardTitle>
            <BrainCircuit className="h-4 w-4 text-indigo-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-white">
              {prediction?.signal || 'HOLD'}
            </div>
            <div className="flex items-center gap-2 mt-1">
              <Badge variant={prediction?.signal === 'BUY' ? 'success' : prediction?.signal === 'SELL' ? 'danger' : 'outline'}>
                {prediction?.confidence ? (prediction.confidence * 100).toFixed(1) + '%' : '--%'}
              </Badge>
              <span className="text-xs text-slate-500">Confidence</span>
            </div>
          </CardContent>
        </Card>

        <Card className="col-span-12 md:col-span-6 lg:col-span-3">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-slate-400">Total Equity</CardTitle>
            <Wallet className="h-4 w-4 text-indigo-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-white">
              ${portfolioStatus?.current_equity?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) || '0.00'}
            </div>
            <div className="flex items-center gap-2 mt-1">
              <span className={`text-xs font-medium ${pnlPercent >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                {pnlPercent >= 0 ? '+' : ''}{pnlPercent.toFixed(2)}%
              </span>
              <span className="text-xs text-slate-500">All time</span>
            </div>
          </CardContent>
        </Card>

        <Card className="col-span-12 md:col-span-6 lg:col-span-3">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-slate-400">Live Price ({symbol})</CardTitle>
            <TrendingUp className="h-4 w-4 text-indigo-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-white font-mono">
              ${livePrice ? livePrice.toFixed(2) : '---'}
            </div>
            <p className="text-xs text-slate-500 mt-1">Binance WebSocket</p>
          </CardContent>
        </Card>

        <Card className="col-span-12 md:col-span-6 lg:col-span-3">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-slate-400">System Risk</CardTitle>
            <AlertTriangle className={`h-4 w-4 ${riskStatus?.risk_level === 'high' ? 'text-rose-400' : 'text-emerald-400'}`} />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold capitalize text-white">
              {riskStatus?.risk_level || 'Normal'}
            </div>
            <div className="flex items-center gap-2 mt-1">
              <Badge variant={riskStatus?.kill_switch ? 'danger' : 'success'}>
                {riskStatus?.kill_switch ? 'Kill Switch Active' : 'Trading Active'}
              </Badge>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-12 lg:col-span-8 flex flex-col gap-4">
          <div className="h-[400px]">
            <TVChart />
          </div>
          <div className="flex-1 h-[250px]">
            <NewsFeed />
          </div>
        </div>

        <div className="col-span-12 lg:col-span-4 flex flex-col gap-4">
          <Card className="flex-1">
            <CardHeader>
              <CardTitle>AI Market Intelligence</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="flex justify-between items-center border-b border-slate-800 pb-2">
                <span className="text-sm text-slate-400">Market Regime</span>
                <span className="text-sm font-mono text-slate-200 capitalize">{typeof prediction?.regime === 'object' ? prediction?.regime?.label : (prediction?.regime || 'Unknown')}</span>
              </div>
              <div className="flex justify-between items-center border-b border-slate-800 pb-2">
                <span className="text-sm text-slate-400">ML Probability (Up)</span>
                <span className="text-sm font-mono text-slate-200">
                  {prediction?.probability 
                    ? (prediction.probability * 100).toFixed(1) + '%' 
                    : '--'}
                </span>
              </div>
              <div className="flex justify-between items-center pb-2">
                <span className="text-sm text-slate-400">News Sentiment</span>
                <span className="text-sm font-mono text-slate-200 capitalize">
                  {/* TODO: Connect to explicit sentiment API if needed */}
                  Neutral
                </span>
              </div>
            </CardContent>
          </Card>

          <div className="flex-1">
            <StrategyTable />
          </div>

          <div className="h-[400px]">
            <OrderBook />
          </div>
        </div>
      </div>
    </div>
  );
}
