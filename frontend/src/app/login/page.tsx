"use client";

import axios from "axios";
import { FormEvent, useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiService } from "@/services/api";
import { useAuthStore } from "@/store/authStore";

export default function LoginPage() {
  const router = useRouter();
  const { token, hydrated, hydrate, setSession } = useAuthStore();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  useEffect(() => {
    if (!hydrated) return;
    if (token) {
      router.replace("/dashboard");
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
        router.replace("/dashboard");
      })
      .catch(() => {
        // No active session cookie on initial load.
      });

    return () => {
      mounted = false;
    };
  }, [hydrated, token, router, setSession]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSuccess(null);

    if (mode === "signup" && password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    if (mode === "signup" && password.length < 10) {
      setError("Password must be at least 10 characters");
      return;
    }

    if (
      mode === "signup" &&
      (!/[A-Za-z]/.test(password) || !/[0-9]/.test(password))
    ) {
      setError("Password must include at least one letter and one number");
      return;
    }

    setLoading(true);
    try {
      if (mode === "signup") {
        await apiService.signup(email, password);
        setSuccess("Account created successfully. Signing in...");
        await apiService.login(email, password);
        const me = (await apiService.getMe()) as {
          email?: string;
          role?: string;
        };
        setSession("session", {
          email: me?.email || email,
          role: me?.role || "user",
        });
        router.push("/dashboard");
      } else {
        await apiService.login(email, password);
        const me = (await apiService.getMe()) as {
          email?: string;
          role?: string;
        };
        setSession("session", {
          email: me?.email || email,
          role: me?.role || "user",
        });
        router.push("/dashboard");
      }
    } catch (err) {
      if (axios.isAxiosError(err)) {
        const detail = err.response?.data as { detail?: string } | undefined;
        setError(detail?.detail || err.message || "Authentication failed");
      } else {
        setError(err instanceof Error ? err.message : "Authentication failed");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid min-h-screen place-items-center bg-[radial-gradient(circle_at_20%_20%,rgba(34,211,238,0.12),transparent_42%),radial-gradient(circle_at_80%_20%,rgba(168,85,247,0.1),transparent_45%),#020617] px-4">
      <motion.form
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        onSubmit={onSubmit}
        className="relative w-full max-w-md rounded-2xl border border-white/10 bg-slate-950/80 p-8 shadow-[0_30px_90px_-20px_rgba(8,145,178,0.4)] backdrop-blur-xl"
      >
        {/* Logo */}
        <div className="mb-6 text-center">
          <h1 className="text-3xl font-bold tracking-tight">
            <span className="bg-linear-to-r from-cyan-300 to-purple-400 bg-clip-text text-transparent">
              VISION AI
            </span>
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            {mode === "login"
              ? "Secure access to institutional trading workspace"
              : "Create your trading account"}
          </p>
        </div>

        {/* Tab Switcher */}
        <div className="mb-6 flex rounded-lg border border-white/10 bg-slate-900/80 p-1">
          {(["login", "signup"] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => {
                setMode(tab);
                setError(null);
                setSuccess(null);
              }}
              className={`flex-1 rounded-md px-3 py-2 text-xs font-semibold uppercase tracking-widest transition-all ${
                mode === tab
                  ? "bg-cyan-500/15 text-cyan-300"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {tab === "login" ? "Login" : "Sign Up"}
            </button>
          ))}
        </div>

        <div className="space-y-4">
          <div>
            <label className="mb-1.5 block text-[11px] uppercase tracking-[0.15em] text-slate-500">
              Email
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-lg border border-white/10 bg-slate-900/90 px-3.5 py-2.5 text-sm text-slate-100 outline-none ring-cyan-500/40 transition focus:border-cyan-500/50 focus:ring-2"
              placeholder="operator@hedgefund.com"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-[11px] uppercase tracking-[0.15em] text-slate-500">
              Password
            </label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-white/10 bg-slate-900/90 px-3.5 py-2.5 text-sm text-slate-100 outline-none ring-cyan-500/40 transition focus:border-cyan-500/50 focus:ring-2"
              placeholder="••••••••"
            />
          </div>

          <AnimatePresence>
            {mode === "signup" && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden"
              >
                <label className="mb-1.5 block text-[11px] uppercase tracking-[0.15em] text-slate-500">
                  Confirm Password
                </label>
                <input
                  type="password"
                  required={mode === "signup"}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="w-full rounded-lg border border-white/10 bg-slate-900/90 px-3.5 py-2.5 text-sm text-slate-100 outline-none ring-cyan-500/40 transition focus:border-cyan-500/50 focus:ring-2"
                  placeholder="••••••••"
                />
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {error && (
          <motion.p
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-300"
          >
            {error}
          </motion.p>
        )}

        {success && (
          <motion.p
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            className="mt-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300"
          >
            {success}
          </motion.p>
        )}

        <button
          type="submit"
          disabled={loading}
          className="mt-6 w-full rounded-lg border border-cyan-400/50 bg-linear-to-r from-cyan-500/20 to-blue-500/20 px-4 py-2.5 text-sm font-semibold text-cyan-100 transition-all hover:from-cyan-500/30 hover:to-blue-500/30 hover:shadow-[0_0_30px_rgba(34,211,238,0.15)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading
            ? "Processing..."
            : mode === "login"
              ? "Access Terminal"
              : "Create Account"}
        </button>

        <p className="mt-4 text-center text-xs text-slate-500">
          <Link
            href="/"
            className="text-slate-400 hover:text-cyan-400 transition"
          >
            ← Back to Home
          </Link>
        </p>
      </motion.form>
    </div>
  );
}
