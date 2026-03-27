"use client";

import { bindAuthExpiryListener, useAuthStore } from "@/store/authStore";
import { apiService } from "@/services/api";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { token, hydrated, hydrate, setSession, logout } = useAuthStore();

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  useEffect(() => {
    const unbind = bindAuthExpiryListener();
    return () => unbind();
  }, []);

  useEffect(() => {
    if (!hydrated) return;

    if (token) {
      return;
    }

    let mounted = true;
    apiService
      .getMe()
      .then((me) => {
        if (!mounted) return;
        setSession("session", {
          email: String((me as { email?: string }).email || "user"),
          role: String((me as { role?: string }).role || "user"),
        });
      })
      .catch(() => {
        if (!mounted) return;
        logout();
        router.replace("/login");
        if (
          typeof window !== "undefined" &&
          window.location.pathname !== "/login"
        ) {
          window.location.href = "/login";
        }
      });

    return () => {
      mounted = false;
    };
  }, [hydrated, logout, router, setSession, token]);

  useEffect(() => {
    if (!hydrated) return;
    if (!token) {
      return;
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
