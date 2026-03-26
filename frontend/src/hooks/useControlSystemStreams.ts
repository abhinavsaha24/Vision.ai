"use client";

import { useEffect } from "react";
import { controlApi } from "@/services/api/controlApi";
import { logger } from "@/services/logger";
import { StreamManager } from "@/services/websocket/streamManager";
import { useAuthStore } from "@/store/authStore";
import { useControlSystemStore } from "@/store/controlSystemStore";

export function useControlSystemStreams() {
  const token = useAuthStore((state) => state.token);
  const symbol = useControlSystemStore((state) => state.symbol);
  const ingestMarket = useControlSystemStore((state) => state.ingestMarket);
  const ingestSignal = useControlSystemStore((state) => state.ingestSignal);
  const ingestPortfolio = useControlSystemStore(
    (state) => state.ingestPortfolio,
  );
  const ingestMetrics = useControlSystemStore((state) => state.ingestMetrics);
  const setExecutions = useControlSystemStore((state) => state.setExecutions);
  const setSystemReadinessScore = useControlSystemStore(
    (state) => state.setSystemReadinessScore,
  );
  const setRiskState = useControlSystemStore((state) => state.setRiskState);
  const setMetaAlpha = useControlSystemStore((state) => state.setMetaAlpha);
  const setStrategies = useControlSystemStore((state) => state.setStrategies);
  const setEngineState = useControlSystemStore((state) => state.setEngineState);
  const setHealthStatus = useControlSystemStore(
    (state) => state.setHealthStatus,
  );
  const appendLog = useControlSystemStore((state) => state.appendLog);

  useEffect(() => {
    if (!token) {
      appendLog(
        `${new Date().toISOString()} stream session paused: missing auth token`,
      );
      return;
    }

    const marketStream = new StreamManager<Record<string, unknown>>({
      channel: "market",
      symbol,
    });
    const signalStream = new StreamManager<Record<string, unknown>>({
      channel: "signals",
      symbol,
    });
    const portfolioStream = new StreamManager<Record<string, unknown>>({
      channel: "portfolio",
    });
    const metricsStream = new StreamManager<Record<string, unknown>>({
      channel: "metrics",
    });

    const unsubs = [
      marketStream.subscribePayload((batch) => {
        batch.forEach((payload) => ingestMarket(payload));
      }),
      signalStream.subscribePayload((batch) => {
        batch.forEach((payload) => ingestSignal(payload));
      }),
      portfolioStream.subscribePayload((batch) => {
        batch.forEach((payload) => ingestPortfolio(payload));
      }),
      metricsStream.subscribePayload((batch) => {
        batch.forEach((payload) => ingestMetrics(payload));
      }),
      marketStream.subscribeStatus(setHealthStatus),
      signalStream.subscribeStatus(setHealthStatus),
      portfolioStream.subscribeStatus(setHealthStatus),
      metricsStream.subscribeStatus(setHealthStatus),
    ];

    marketStream.start();
    signalStream.start();
    portfolioStream.start();
    metricsStream.start();

    const timer = setInterval(() => {
      Promise.allSettled([
        controlApi.getOrders(120),
        controlApi.getSystemReadiness(),
        controlApi.getSystemRisk(),
        controlApi.getMetaAlpha(symbol, 5),
        controlApi.getStrategies(),
        controlApi.getWorkersStatus(),
        controlApi.getPaperStatus(),
      ]).then((results) => {
        const [
          orders,
          readiness,
          risk,
          metaAlpha,
          strategies,
          workers,
          engine,
        ] = results;

        if (orders.status === "fulfilled") {
          setExecutions(orders.value.historyOrders, orders.value.activeOrders);
        }

        if (readiness.status === "fulfilled") {
          const score = Number(
            readiness.value.overall_score ?? readiness.value.score ?? 0,
          );
          setSystemReadinessScore(score);
        }

        if (risk.status === "fulfilled") {
          setRiskState(risk.value as Record<string, unknown>);
        }

        if (metaAlpha.status === "fulfilled") {
          setMetaAlpha(metaAlpha.value as Record<string, unknown>);
        }

        if (strategies.status === "fulfilled") {
          setStrategies(strategies.value);
        }

        if (workers.status === "fulfilled" || engine.status === "fulfilled") {
          setEngineState({
            workers: workers.status === "fulfilled" ? workers.value : null,
            paper: engine.status === "fulfilled" ? engine.value : null,
          });
        }
      });
    }, 5000);

    appendLog(
      `${new Date().toISOString()} stream session started for ${symbol}`,
    );

    return () => {
      clearInterval(timer);
      unsubs.forEach((unsub) => unsub());
      marketStream.stop();
      signalStream.stop();
      portfolioStream.stop();
      metricsStream.stop();
      appendLog(
        `${new Date().toISOString()} stream session stopped for ${symbol}`,
      );
    };
  }, [
    token,
    appendLog,
    ingestMarket,
    ingestMetrics,
    ingestPortfolio,
    ingestSignal,
    setEngineState,
    setExecutions,
    setHealthStatus,
    setMetaAlpha,
    setRiskState,
    setStrategies,
    setSystemReadinessScore,
    symbol,
  ]);

  useEffect(() => {
    controlApi
      .getModelRegistry()
      .then((data) => {
        appendLog(
          `${new Date().toISOString()} model version ${String((data as Record<string, unknown>).active_version ?? "unknown")}`,
        );
      })
      .catch((error) => {
        logger.warn({ message: "Could not load model registry", error });
      });
  }, [appendLog]);
}
