"use client";

import { useSignalStore } from "@/store/signalStore";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Activity } from "lucide-react";

export default function PredictionsPage() {
  const { prediction } = useSignalStore();


  return (
    <div className="flex flex-col gap-6 max-w-6xl mx-auto">
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold tracking-tight text-white">ML Predictions</h1>
        <p className="text-slate-400">Deep learning predictions across different time horizons.</p>
      </div>

      <div className="grid grid-cols-1 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Forecast Probabilities</CardTitle>
          </CardHeader>
          <CardContent>
            {prediction ? (
              <div className="flex flex-col gap-4">
                <div className="flex items-center gap-6 p-4 rounded-xl bg-slate-800/30 border border-slate-700/50">
                  <div className="flex flex-col w-24">
                    <span className="text-xs text-slate-500 uppercase font-semibold tracking-wider">Step</span>
                    <span className="text-lg font-mono text-white">+5</span>
                  </div>

                  <div className="flex-1">
                    <div className="flex justify-between items-center mb-2">
                      <span className="text-sm font-medium text-slate-300">Upward Probability</span>
                      <span className="text-sm font-mono text-indigo-400">{(prediction.probability * 100).toFixed(1)}%</span>
                    </div>
                    <div className="h-2 w-full bg-slate-800 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-gradient-to-r from-cyan-500 to-indigo-500 rounded-full" 
                        style={{ width: `${prediction.probability * 100}%` }}
                      />
                    </div>
                  </div>

                  <div className="flex flex-col w-32 items-end">
                    <span className="text-xs text-slate-500 uppercase font-semibold tracking-wider">Regime</span>
                    <span className="text-sm font-medium text-slate-300 capitalize">{typeof prediction.regime === 'object' ? prediction.regime?.label : prediction.regime}</span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="py-12 text-center text-slate-500">
                Waiting for prediction data...
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
