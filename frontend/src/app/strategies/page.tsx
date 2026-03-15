"use client";

import { StrategyTable } from "@/components/dashboard/StrategyTable";

export default function StrategiesPage() {
  return (
    <div className="flex flex-col gap-6 max-w-5xl mx-auto h-full">
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold tracking-tight text-white">Active Strategies</h1>
        <p className="text-slate-400">Monitor and manage quantitative trading algorithms running in real-time.</p>
      </div>

      <div className="flex-1 min-h-[600px]">
        <StrategyTable />
      </div>
    </div>
  );
}
