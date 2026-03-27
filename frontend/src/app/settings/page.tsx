"use client";

import { useEffect, useState } from "react";
import { apiService } from "@/services/api";
import { AuthGuard } from "@/components/dashboard/auth-guard";
import { TerminalCard } from "@/components/ui/terminal-card";
import { useAuthStore } from "@/store/authStore";

export default function SettingsPage() {
  const logout = useAuthStore((state) => state.logout);
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [readiness, setReadiness] = useState<Record<string, unknown> | null>(
    null,
  );

  useEffect(() => {
    async function load() {
      try {
        const [h, r] = await Promise.all([
          apiService.getHealth(),
          apiService.getSystemReadiness(),
        ]);
        setHealth(h as Record<string, unknown>);
        setReadiness(r as Record<string, unknown>);
      } catch (err) {
        console.error(err);
      }
    }
    load();
  }, []);

  return (
    <AuthGuard>
      <div className="mx-auto max-w-5xl space-y-4 px-4 py-6 md:px-6">
        <TerminalCard
          title="Control Center"
          right={
            <button
              onClick={async () => {
                try {
                  await apiService.logout();
                } catch {
                  // Continue with local logout even if backend logout fails.
                }
                logout();
                window.location.href = "/login";
              }}
              className="rounded-md border border-rose-500/50 bg-rose-500/10 px-3 py-1 text-xs font-semibold text-rose-200"
            >
              Logout
            </button>
          }
        >
          <p className="text-sm text-slate-300">
            Authenticated operational controls and readiness diagnostics.
          </p>
        </TerminalCard>

        <div className="grid gap-4 lg:grid-cols-2">
          <TerminalCard title="Backend Health">
            <pre className="max-h-80 overflow-auto rounded-lg border border-white/10 bg-slate-950/70 p-3 text-xs text-emerald-300">
              {JSON.stringify(health, null, 2)}
            </pre>
          </TerminalCard>

          <TerminalCard title="System Readiness">
            <pre className="max-h-80 overflow-auto rounded-lg border border-white/10 bg-slate-950/70 p-3 text-xs text-cyan-200">
              {JSON.stringify(readiness, null, 2)}
            </pre>
          </TerminalCard>
        </div>
      </div>
    </AuthGuard>
  );
}
