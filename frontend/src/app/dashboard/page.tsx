"use client";

import { AuthGuard } from "@/components/dashboard/auth-guard";
import { TradingTerminal } from "@/components/dashboard/trading-terminal";

export default function DashboardPage() {
  return (
    <AuthGuard>
      <div className="mx-auto max-w-112.5 px-4 py-5 md:px-6">
        <TradingTerminal />
      </div>
    </AuthGuard>
  );
}
