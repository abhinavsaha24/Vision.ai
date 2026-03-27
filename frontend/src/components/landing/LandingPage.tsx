"use client";

import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { useRouter } from "next/navigation";
import { ParticleField } from "@/components/landing/ParticleField";
import { AuthModal } from "@/components/landing/AuthModal";
import { apiService } from "@/services/api";
import { useAuthStore } from "@/store/authStore";

/* ── Fade-up animation variants ── */
const fadeUp = {
  hidden: { opacity: 0, y: 30 },
  visible: (delay: number) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.7, delay, ease: [0.25, 0.1, 0.25, 1] as const },
  }),
};

const stagger = {
  visible: { transition: { staggerChildren: 0.12 } },
};

/* ── Feature cards data ── */
const FEATURES = [
  {
    icon: "⚡",
    title: "Microstructure Intelligence",
    desc: "Sub-second order book analysis with real-time spread, imbalance, and depth monitoring across venues.",
  },
  {
    icon: "🧠",
    title: "AI Alpha Engine",
    desc: "Ensemble ML models combining regime detection, signal generation, and confidence scoring for directional alpha.",
  },
  {
    icon: "📊",
    title: "Real-Time Data Streams",
    desc: "Native WebSocket feeds with auto-reconnect, heartbeat monitoring, and zero-latency market data propagation.",
  },
  {
    icon: "🛡️",
    title: "Institutional Risk Management",
    desc: "Multi-layer risk framework with circuit breakers, VaR monitoring, drawdown limits, and kill-switch protection.",
  },
  {
    icon: "🔬",
    title: "Quantitative Research",
    desc: "Factor analysis, strategy backtesting with realistic cost modeling, and walk-forward optimization pipeline.",
  },
  {
    icon: "🚀",
    title: "Execution Engine",
    desc: "Smart order routing with paper and live trading modes, slippage tracking, and execution quality metrics.",
  },
];

/* ── Vision items ── */
const VISION_ITEMS = [
  {
    title: "Market as a Complex System",
    text: "Financial markets are nonlinear dynamical systems. We model them as such — using regime detection, drift monitoring, and adaptive strategies that evolve with market conditions.",
  },
  {
    title: "Alpha Through Understanding",
    text: "True edge comes not from speed alone, but from deeper understanding. Our microstructure intelligence extracts signals invisible to traditional analysis.",
  },
  {
    title: "Risk-First Architecture",
    text: "Every basis point of exposure is measured, monitored, and managed. Our institutional-grade risk framework ensures capital preservation is never compromised.",
  },
];

export function LandingPage() {
  const router = useRouter();
  const { token, hydrated, hydrate, setSession } = useAuthStore();
  const [authOpen, setAuthOpen] = useState(false);

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
        // Not authenticated, keep landing page.
      });

    return () => {
      mounted = false;
    };
  }, [hydrated, router, setSession, token]);

  const handleAuthSuccess = () => {
    setAuthOpen(false);
    router.push("/dashboard");
  };

  return (
    <div className="relative min-h-screen overflow-hidden bg-[#020617]">
      <ParticleField />

      {/* ════════════════ HERO ════════════════ */}
      <section className="relative z-10 flex min-h-screen flex-col items-center justify-center px-6 text-center">
        {/* Radial gradient accents */}
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,rgba(34,211,238,0.12),transparent_40%),radial-gradient(circle_at_70%_80%,rgba(168,85,247,0.1),transparent_40%)]" />

        <motion.div
          initial="hidden"
          animate="visible"
          variants={stagger}
          className="relative"
        >
          {/* Badge */}
          <motion.div
            variants={fadeUp}
            custom={0}
            className="mx-auto mb-6 inline-flex items-center gap-2 rounded-full border border-cyan-400/30 bg-cyan-500/10 px-4 py-1.5 text-xs font-medium tracking-widest text-cyan-300 uppercase backdrop-blur-sm"
          >
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-cyan-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-cyan-400" />
            </span>
            Institutional Trading Platform
          </motion.div>

          {/* Title */}
          <motion.h1
            variants={fadeUp}
            custom={0.15}
            className="text-6xl font-bold tracking-tight sm:text-7xl md:text-8xl lg:text-9xl"
          >
            <span className="bg-gradient-to-r from-cyan-300 via-blue-400 to-purple-400 bg-clip-text text-transparent glow-text-cyan">
              VISION
            </span>{" "}
            <span className="bg-gradient-to-r from-purple-400 to-cyan-300 bg-clip-text text-transparent glow-text-purple">
              AI
            </span>
          </motion.h1>

          {/* Tagline */}
          <motion.p
            variants={fadeUp}
            custom={0.3}
            className="mt-4 text-lg font-medium tracking-[0.2em] text-slate-400 uppercase sm:text-xl"
          >
            Microstructure Intelligence Engine
          </motion.p>

          {/* Sub-tagline */}
          <motion.p
            variants={fadeUp}
            custom={0.45}
            className="mx-auto mt-6 max-w-2xl text-base text-slate-400/80 leading-relaxed"
          >
            An AI-powered quantitative trading system that combines real-time
            microstructure analysis, ensemble machine learning, and
            institutional-grade risk management to generate alpha in digital
            asset markets.
          </motion.p>

          {/* CTA Buttons */}
          <motion.div
            variants={fadeUp}
            custom={0.6}
            className="mt-10 flex flex-col items-center gap-4 sm:flex-row sm:justify-center"
          >
            <button
              onClick={() => setAuthOpen(true)}
              className="group relative rounded-xl border border-cyan-400/50 bg-gradient-to-r from-cyan-500/20 to-blue-500/20 px-8 py-3.5 text-sm font-semibold tracking-wide text-cyan-100 transition-all hover:from-cyan-500/30 hover:to-blue-500/30 hover:shadow-[0_0_40px_rgba(34,211,238,0.2)]"
            >
              <span className="relative z-10">Launch Terminal</span>
            </button>
            <a
              href="#about"
              className="rounded-xl border border-white/10 bg-white/5 px-8 py-3.5 text-sm font-medium tracking-wide text-slate-300 transition-all hover:border-white/20 hover:bg-white/10"
            >
              Learn More
            </a>
          </motion.div>
        </motion.div>

        {/* Scroll indicator */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1.5, duration: 1 }}
          className="absolute bottom-8 left-1/2 -translate-x-1/2"
        >
          <div className="flex flex-col items-center gap-2 text-slate-500">
            <span className="text-[10px] uppercase tracking-[0.2em]">
              Scroll
            </span>
            <svg
              width="16"
              height="24"
              viewBox="0 0 16 24"
              fill="none"
              className="animate-bounce"
            >
              <rect
                x="4.5"
                y="0.5"
                width="7"
                height="12"
                rx="3.5"
                stroke="currentColor"
              />
              <circle
                cx="8"
                cy="5"
                r="1.5"
                fill="currentColor"
                className="animate-pulse"
              />
              <path
                d="M8 16L4 20L8 24L12 20L8 16Z"
                fill="currentColor"
                opacity="0.3"
              />
            </svg>
          </div>
        </motion.div>
      </section>

      {/* ════════════════ ABOUT ════════════════ */}
      <section id="about" className="relative z-10 px-6 py-24 md:py-32">
        <div className="mx-auto max-w-6xl">
          <motion.div
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, margin: "-100px" }}
            variants={stagger}
          >
            <motion.div
              variants={fadeUp}
              custom={0}
              className="text-center mb-16"
            >
              <h2 className="text-3xl font-bold tracking-tight text-slate-100 sm:text-4xl">
                The System
              </h2>
              <p className="mt-4 mx-auto max-w-2xl text-slate-400">
                Built for systematic alpha generation — from raw market data to
                execution, every layer is designed for reliability and edge.
              </p>
            </motion.div>

            <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
              {FEATURES.map((feature, i) => (
                <motion.div
                  key={feature.title}
                  variants={fadeUp}
                  custom={i * 0.08}
                  className="group rounded-xl border border-white/8 bg-slate-900/50 p-6 backdrop-blur-sm transition-all hover:border-cyan-400/25 hover:bg-slate-900/70 hover:shadow-[0_0_30px_rgba(34,211,238,0.06)]"
                >
                  <span className="text-2xl">{feature.icon}</span>
                  <h3 className="mt-3 text-base font-semibold text-slate-100">
                    {feature.title}
                  </h3>
                  <p className="mt-2 text-sm leading-relaxed text-slate-400">
                    {feature.desc}
                  </p>
                </motion.div>
              ))}
            </div>
          </motion.div>
        </div>
      </section>

      {/* ════════════════ VISION ════════════════ */}
      <section className="relative z-10 px-6 py-24 md:py-32">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_50%,rgba(168,85,247,0.06),transparent_50%)]" />
        <div className="mx-auto max-w-4xl">
          <motion.div
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, margin: "-100px" }}
            variants={stagger}
          >
            <motion.div
              variants={fadeUp}
              custom={0}
              className="text-center mb-16"
            >
              <h2 className="text-3xl font-bold tracking-tight text-slate-100 sm:text-4xl">
                Our Vision
              </h2>
              <p className="mt-4 mx-auto max-w-2xl text-slate-400">
                A philosophical approach to quantitative trading — where
                technology meets deep market understanding.
              </p>
            </motion.div>

            <div className="space-y-8">
              {VISION_ITEMS.map((item, i) => (
                <motion.div
                  key={item.title}
                  variants={fadeUp}
                  custom={i * 0.12}
                  className="rounded-xl border border-white/8 bg-slate-900/40 p-8 backdrop-blur-sm"
                >
                  <h3 className="text-lg font-semibold text-cyan-300">
                    {item.title}
                  </h3>
                  <p className="mt-3 text-sm leading-relaxed text-slate-300/80">
                    {item.text}
                  </p>
                </motion.div>
              ))}
            </div>
          </motion.div>
        </div>
      </section>

      {/* ════════════════ FOOTER ════════════════ */}
      <footer className="relative z-10 border-t border-white/6 px-6 py-16">
        <div className="mx-auto max-w-6xl">
          <div className="grid gap-12 md:grid-cols-3">
            {/* Brand */}
            <div>
              <h3 className="text-lg font-bold">
                <span className="bg-gradient-to-r from-cyan-300 to-purple-400 bg-clip-text text-transparent">
                  VISION AI
                </span>
              </h3>
              <p className="mt-3 text-sm text-slate-500 leading-relaxed">
                Institutional-grade AI quantitative trading platform. Built for
                precision, reliability, and alpha.
              </p>
            </div>

            {/* Links */}
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-[0.15em] text-slate-400 mb-4">
                Links
              </h4>
              <ul className="space-y-2.5 text-sm">
                <li>
                  <a
                    href="https://github.com/AbhinavSaha24"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-slate-400 transition hover:text-cyan-300"
                  >
                    GitHub
                  </a>
                </li>
                <li>
                  <a
                    href="https://www.linkedin.com/in/abhinavsaha24"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-slate-400 transition hover:text-cyan-300"
                  >
                    LinkedIn
                  </a>
                </li>
                <li>
                  <a
                    href="mailto:abhinavsaha24@gmail.com"
                    className="text-slate-400 transition hover:text-cyan-300"
                  >
                    Contact
                  </a>
                </li>
              </ul>
            </div>

            {/* Legal */}
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-[0.15em] text-slate-400 mb-4">
                Legal
              </h4>
              <ul className="space-y-2.5 text-sm">
                <li>
                  <span className="text-slate-500">Privacy Policy</span>
                </li>
                <li>
                  <span className="text-slate-500">Terms of Service</span>
                </li>
                <li>
                  <span className="text-slate-500">MIT License</span>
                </li>
              </ul>
            </div>
          </div>

          <div className="mt-12 flex flex-col items-center justify-between gap-4 border-t border-white/6 pt-8 md:flex-row">
            <p className="text-xs text-slate-600">
              © {new Date().getFullYear()} Vision AI. All rights reserved.
            </p>
            <p className="text-xs text-slate-600">
              Built by{" "}
              <a
                href="https://github.com/AbhinavSaha24"
                target="_blank"
                rel="noopener noreferrer"
                className="text-slate-400 hover:text-cyan-400 transition"
              >
                Abhinav Saha
              </a>
            </p>
          </div>
        </div>
      </footer>

      {/* Auth Modal */}
      <AuthModal
        isOpen={authOpen}
        onClose={() => setAuthOpen(false)}
        onSuccess={handleAuthSuccess}
      />
    </div>
  );
}
