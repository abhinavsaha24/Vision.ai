import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { PlayCircle, StopCircle, RefreshCcw, DollarSign, Clock, AlertTriangle, Activity } from "lucide-react";
import { useMarketStore } from "@/store/marketStore";
import { apiService } from "@/services/api";

export function PaperTradingControl() {
  const { symbol } = useMarketStore();
  const [status, setStatus] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form states
  const [initialCash, setInitialCash] = useState(10000);
  const [intervalSecs, setIntervalSecs] = useState(300);

  const fetchStatus = async () => {
    try {
      const data = await apiService.getPaperStatus();
      setStatus(data);
      setError(null);
    } catch (err: any) {
      setError("Failed to fetch status");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleStart = async () => {
    setStarting(true);
    setError(null);
    try {
      await apiService.startPaperTrading(symbol, initialCash, intervalSecs);
      await fetchStatus();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to start simulation");
    } finally {
      setStarting(false);
    }
  };

  const isRunning = status?.is_running;

  return (
    <Card className="bg-slate-900 border-slate-800">
      <CardHeader className="pb-4 border-b border-slate-800/50">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-lg flex items-center gap-2">
              <PlayCircle className="h-5 w-5 text-indigo-400" />
              Paper Trading Simulation
            </CardTitle>
            <CardDescription className="mt-1">
              Test strategies in real-time with virtual funds
            </CardDescription>
          </div>
          <div className="flex gap-2">
            <button 
              onClick={fetchStatus} 
              className="p-2 bg-slate-800 hover:bg-slate-700 rounded-lg transition-colors text-slate-400 hover:text-white"
              disabled={loading}
            >
              <RefreshCcw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>
      </CardHeader>
      
      <CardContent className="pt-6">
        {error && (
          <div className="mb-4 p-3 bg-rose-500/10 border border-rose-500/20 rounded-lg flex items-start gap-2 text-rose-400 text-sm">
            <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
            <p>{error}</p>
          </div>
        )}

        {isRunning ? (
          <div className="flex flex-col items-center justify-center py-6 bg-emerald-500/5 border border-emerald-500/10 rounded-xl gap-4">
            <div className="relative">
              <div className="absolute inset-0 bg-emerald-400 blur-md opacity-20 animate-pulse rounded-full" />
              <Activity className="h-10 w-10 text-emerald-400 relative z-10" />
            </div>
            <div className="text-center">
              <h3 className="text-emerald-400 font-bold text-lg">Simulation Running</h3>
              <p className="text-slate-400 text-sm font-mono mt-1">Trading {symbol} live</p>
            </div>
            <button 
              className="mt-2 px-6 py-2 bg-rose-500/10 text-rose-400 hover:bg-rose-500/20 font-medium rounded-lg transition-colors flex items-center gap-2"
              onClick={() => alert('Stop API not implemented yet. Please restart backend.')}
            >
              <StopCircle className="h-4 w-4" />
              Stop Engine
            </button>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="flex flex-col gap-2">
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                  <DollarSign className="h-3 w-3" /> Initial Cash
                </label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 font-mono">$</span>
                  <input 
                    type="number" 
                    value={initialCash}
                    onChange={(e) => setInitialCash(Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-8 pr-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all"
                  />
                </div>
              </div>
              <div className="flex flex-col gap-2">
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                  <Clock className="h-3 w-3" /> Trade Interval
                </label>
                <div className="relative">
                  <input 
                    type="number" 
                    value={intervalSecs}
                    onChange={(e) => setIntervalSecs(Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-3 pr-8 py-2 text-sm text-white font-mono focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all"
                  />
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 font-mono">sec</span>
                </div>
              </div>
            </div>
            
            <button 
              disabled={starting}
              onClick={handleStart}
              className="w-full mt-2 bg-indigo-600 hover:bg-indigo-500 text-white font-medium py-2.5 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex justify-center items-center gap-2"
            >
              {starting ? (
                <>
                  <RefreshCcw className="h-4 w-4 animate-spin" />
                  Booting Engine...
                </>
              ) : (
                <>
                  <PlayCircle className="h-4 w-4" />
                  Start {symbol} Simulation
                </>
              )}
            </button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
