import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Layers, Activity } from "lucide-react";
import { apiService } from "@/services/api";

interface Strategy {
  key?: string;
  name: string;
  active: boolean;
  weight: number;
}

export function StrategyTable() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    async function fetchStrategies() {
      try {
        const data = await apiService.getStrategies();
        if (mounted) {
          setStrategies(data?.strategies || []);
          setLoading(false);
        }
      } catch (err) {
        if (mounted) setLoading(false);
      }
    }
    fetchStrategies();
    const interval = setInterval(fetchStrategies, 15000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  const activeCount = strategies.filter((s) => s.active).length;

  return (
    <Card className="flex flex-col h-full bg-slate-900 border-slate-800">
      <CardHeader className="pb-3 flex flex-row items-center justify-between">
        <div>
          <CardTitle className="text-sm font-medium text-slate-200 flex items-center gap-2">
            <Layers className="h-4 w-4 text-indigo-400" />
            Active Strategies
          </CardTitle>
          <CardDescription className="text-xs mt-1">
            Running quantitative models
          </CardDescription>
        </div>
        <div className="bg-indigo-500/10 text-indigo-400 px-2.5 py-1 rounded border border-indigo-500/20 text-[10px] font-mono tracking-widest uppercase">
          {activeCount} / {strategies.length} Active
        </div>
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto">
        {loading && strategies.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-slate-500 gap-3">
            <Activity className="h-5 w-5 animate-pulse" />
            <span className="text-xs font-mono uppercase tracking-widest">Loading Library</span>
          </div>
        ) : strategies.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-slate-500 text-xs font-mono">
            No strategies available.
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {strategies.map((strat, i) => {
              const weightPercent = strat.weight * 100;
              const isML = strat.name.toUpperCase().includes("AI");
              
              return (
                <div key={strat.key || i} className="group flex flex-col gap-1.5 p-2.5 rounded-lg hover:bg-slate-800/50 transition-colors border border-transparent hover:border-slate-800">
                  <div className="flex justify-between items-center">
                    <span className="text-xs font-semibold text-slate-200 uppercase tracking-wider group-hover:text-white transition-colors truncate max-w-[150px]" title={strat.name}>
                      {strat.name.replace(/_/g, " ")}
                    </span>
                    <span className="text-xs font-mono text-slate-400">
                      {weightPercent.toFixed(0)}%
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    {/* Visual Allocation Bar */}
                    <div className="h-1.5 flex-1 bg-slate-800 rounded-full overflow-hidden">
                      <div 
                        className={`h-full rounded-full transition-all duration-500 ${isML ? 'bg-gradient-to-r from-indigo-500 to-cyan-400' : 'bg-gradient-to-r from-emerald-500 to-teal-400'}`}
                        style={{ width: `${weightPercent}%` }}
                      />
                    </div>
                    <span className={`text-[9px] uppercase tracking-wider font-medium px-1.5 py-0.5 rounded ${isML ? 'bg-indigo-500/10 text-indigo-400' : 'bg-emerald-500/10 text-emerald-400'}`}>
                      {isML ? 'ML' : 'Quant'}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
