"use client";

import { FormEvent, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import axios from "axios";
import { apiService } from "@/services/api";
import { useAuthStore } from "@/store/authStore";

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export function AuthModal({ isOpen, onClose, onSuccess }: AuthModalProps) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const { setSession } = useAuthStore();

  const resetForm = () => {
    setEmail("");
    setPassword("");
    setConfirmPassword("");
    setError(null);
    setSuccess(null);
  };

  const switchMode = (newMode: "login" | "signup") => {
    setMode(newMode);
    resetForm();
  };

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
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
        setSuccess("Account created. Signing you in...");
        // Auto-login after signup
        const data = await apiService.login(email, password);
        const tokenValue = data.access_token || data.token;
        if (!tokenValue) throw new Error("Token missing in login response");
        setSession(tokenValue, { email, role: "user" });
        setTimeout(onSuccess, 500);
      } else {
        const data = await apiService.login(email, password);
        const tokenValue = data.access_token || data.token;
        if (!tokenValue) throw new Error("Token missing in login response");
        setSession(tokenValue, { email, role: "user" });
        onSuccess();
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
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="fixed inset-0 z-50 grid place-items-center bg-black/60 backdrop-blur-sm px-4"
          onClick={(e) => {
            if (e.target === e.currentTarget) onClose();
          }}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
            className="w-full max-w-md rounded-2xl border border-white/10 bg-slate-950/85 p-8 shadow-[0_30px_90px_-20px_rgba(8,145,178,0.4)] backdrop-blur-xl"
          >
            {/* Header */}
            <div className="mb-6 text-center">
              <h2 className="text-2xl font-bold tracking-tight text-slate-100">
                {mode === "login" ? "Access Terminal" : "Create Account"}
              </h2>
              <p className="mt-1 text-sm text-slate-400">
                {mode === "login"
                  ? "Secure access to your trading workspace"
                  : "Join the VISION AI trading platform"}
              </p>
            </div>

            {/* Tab switcher */}
            <div className="mb-6 flex rounded-lg border border-white/10 bg-slate-900/80 p-1">
              {(["login", "signup"] as const).map((tab) => (
                <button
                  key={tab}
                  type="button"
                  onClick={() => switchMode(tab)}
                  className={`flex-1 rounded-md px-3 py-2 text-xs font-semibold uppercase tracking-widest transition-all ${
                    mode === tab
                      ? "bg-cyan-500/15 text-cyan-300 shadow-sm"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {tab === "login" ? "Login" : "Sign Up"}
                </button>
              ))}
            </div>

            {/* Form */}
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="mb-1.5 block text-[11px] uppercase tracking-[0.15em] text-slate-500">
                  Email Address
                </label>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="email"
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
                  autoComplete={
                    mode === "login" ? "current-password" : "new-password"
                  }
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
                      autoComplete="new-password"
                      className="w-full rounded-lg border border-white/10 bg-slate-900/90 px-3.5 py-2.5 text-sm text-slate-100 outline-none ring-cyan-500/40 transition focus:border-cyan-500/50 focus:ring-2"
                      placeholder="••••••••"
                    />
                  </motion.div>
                )}
              </AnimatePresence>

              {error && (
                <motion.p
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-300"
                >
                  {error}
                </motion.p>
              )}

              {success && (
                <motion.p
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300"
                >
                  {success}
                </motion.p>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full rounded-lg border border-cyan-400/50 bg-linear-to-r from-cyan-500/20 to-blue-500/20 px-4 py-2.5 text-sm font-semibold text-cyan-100 transition-all hover:from-cyan-500/30 hover:to-blue-500/30 hover:shadow-[0_0_30px_rgba(34,211,238,0.15)] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading
                  ? "Processing..."
                  : mode === "login"
                    ? "Access Terminal"
                    : "Create Account"}
              </button>
            </form>

            {/* Close */}
            <button
              type="button"
              onClick={onClose}
              className="absolute right-4 top-4 rounded-full p-1 text-slate-500 transition hover:bg-white/10 hover:text-slate-300"
              aria-label="Close"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path
                  d="M4 4L12 12M12 4L4 12"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
