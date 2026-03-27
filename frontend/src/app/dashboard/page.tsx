"use client";

import { useRouter } from "next/navigation";
import { AuthGuard } from "@/components/dashboard/auth-guard";
import { GlobalErrorBoundary } from "@/components/system/global-error-boundary";
import { InstitutionalTerminal } from "@/components/dashboard/institutional-terminal";
import { apiService } from "@/services/api";
import { useAuthStore } from "@/store/authStore";

export default function DashboardPage() {
  const router = useRouter();
  const logout = useAuthStore((state) => state.logout);

  const handleLogout = async () => {
    if (!window.confirm("Are you sure you want to log out?")) {
      return;
    }
    try {
      await apiService.logout();
    } catch {
      // Continue with local logout even if backend logout fails.
    }
    logout();
    router.replace("/login");
  };

  return (
    <AuthGuard>
      <div className="mx-auto w-full max-w-screen-2xl px-3 py-3 sm:px-4 md:px-5">
        <GlobalErrorBoundary>
          <InstitutionalTerminal />
        </GlobalErrorBoundary>
        <div className="mt-3 flex justify-end">
          <button
            onClick={handleLogout}
            className="rounded-md border border-rose-500/50 bg-rose-500/10 px-3 py-1.5 text-xs font-semibold text-rose-200 transition hover:bg-rose-500/20"
          >
            Logout
          </button>
        </div>
      </div>
    </AuthGuard>
  );
}
