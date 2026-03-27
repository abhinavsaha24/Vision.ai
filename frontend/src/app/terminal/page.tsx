"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/**
 * /terminal is deprecated — the dashboard IS the terminal now.
 * This page redirects to /dashboard.
 */
export default function TerminalRedirectPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/dashboard");
  }, [router]);

  return (
    <div className="grid min-h-screen place-items-center">
      <p className="text-sm text-slate-500">Redirecting to Dashboard...</p>
    </div>
  );
}
