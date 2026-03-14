"use client";

import { useSignalStore } from "@/store/signalStore";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Activity } from "lucide-react";
import { useEffect, useState } from "react";
import { apiService } from "@/services/api";

export default function SettingsPage() {
  const [health, setHealth] = useState<any>(null);

  useEffect(() => {
    async function load() {
      try {
        const data = await apiService.getHealth();
        setHealth(data);
      } catch (err) {
        console.error(err);
      }
    }
    load();
  }, []);

  return (
    <div className="flex flex-col gap-6 max-w-4xl mx-auto text-white">
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold tracking-tight">System Settings</h1>
        <p className="text-slate-400">Configuration and backend component health.</p>
      </div>

      <Card className="bg-slate-900 border-slate-800">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-5 w-5 text-indigo-400" />
            Backend Detailed Health
          </CardTitle>
        </CardHeader>
        <CardContent>
          {health ? (
             <pre className="bg-slate-950 p-4 rounded-xl border border-slate-800 text-sm font-mono text-emerald-400 overflow-x-auto">
               {JSON.stringify(health, null, 2)}
             </pre>
          ) : (
            <div className="py-8 text-center text-slate-500 font-mono">
              Loading backend health...
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
