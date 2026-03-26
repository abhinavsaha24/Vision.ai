"use client";

import { bindAuthExpiryListener, useAuthStore } from "@/store/authStore";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { token, hydrated, hydrate } = useAuthStore();

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  useEffect(() => {
    const unbind = bindAuthExpiryListener();
    return () => unbind();
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    if (!token) {
      router.replace("/login");
      if (
        typeof window !== "undefined" &&
        window.location.pathname !== "/login"
      ) {
        window.location.href = "/login";
      }
    }
  }, [hydrated, token, router]);

  if (!hydrated || !token) {
    return (
      <div className="grid min-h-[60vh] place-items-center text-slate-300">
        <div className="rounded-xl border border-white/10 bg-slate-900/60 px-6 py-4 text-sm tracking-wide">
          Initializing secure terminal session...
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
