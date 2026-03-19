"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiService } from "@/services/api";
import { useAuthStore } from "@/store/authStore";

export default function LoginPage() {
  const router = useRouter();
  const { token, hydrated, hydrate, setSession } = useAuthStore();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  useEffect(() => {
    if (hydrated && token) {
      router.replace("/dashboard");
    }
  }, [hydrated, token, router]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const data = await apiService.login(email, password);
      const tokenValue = data.access_token || data.token;
      if (!tokenValue) {
        throw new Error("Token missing in login response");
      }
      setSession(tokenValue, { email, role: "user" });
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid min-h-screen place-items-center bg-[radial-gradient(circle_at_20%_20%,rgba(34,211,238,0.15),transparent_42%),radial-gradient(circle_at_80%_20%,rgba(245,158,11,0.18),transparent_45%),#020617] px-4">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-md rounded-2xl border border-white/15 bg-slate-950/70 p-6 shadow-[0_30px_90px_-40px_rgba(8,145,178,0.55)] backdrop-blur-lg"
      >
        <h1 className="text-2xl font-bold tracking-tight text-slate-100">
          Vision AI Terminal Login
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          Secure access to institutional trading workspace
        </p>

        <div className="mt-6 space-y-4">
          <div>
            <label className="mb-2 block text-xs uppercase tracking-[0.14em] text-slate-500">
              Email
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="w-full rounded-lg border border-white/10 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none ring-cyan-500/50 focus:ring-2"
            />
          </div>
          <div>
            <label className="mb-2 block text-xs uppercase tracking-[0.14em] text-slate-500">
              Password
            </label>
            <input
              type="password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="w-full rounded-lg border border-white/10 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none ring-cyan-500/50 focus:ring-2"
            />
          </div>
        </div>

        {error ? <p className="mt-3 text-sm text-rose-300">{error}</p> : null}

        <button
          type="submit"
          disabled={loading}
          className="mt-6 w-full rounded-lg border border-cyan-400/60 bg-cyan-500/15 px-3 py-2 text-sm font-semibold text-cyan-200 transition hover:bg-cyan-500/25 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? "Authenticating..." : "Access Terminal"}
        </button>
      </form>
    </div>
  );
}
