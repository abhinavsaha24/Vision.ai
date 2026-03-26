"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { createRealtimeChannel } from "@/services/websocket";

interface ChannelStatus {
  name: string;
  connected: boolean;
}

interface WebSocketState {
  channels: ChannelStatus[];
  reconnectCount: number;
  messagesReceived: number;
  lastLatencyMs: number | null;
}

/**
 * Hook managing all 4 WebSocket channels for the trading terminal.
 * Provides connection status, message counts, and data handlers.
 */
export function useTerminalWebSocket(
  symbol: string,
  handlers: {
    onMarket?: (data: unknown) => void;
    onSignal?: (data: unknown) => void;
    onPortfolio?: (data: unknown) => void;
    onMetrics?: (data: unknown) => void;
  },
) {
  const [state, setState] = useState<WebSocketState>({
    channels: [
      { name: "market", connected: false },
      { name: "signals", connected: false },
      { name: "portfolio", connected: false },
      { name: "metrics", connected: false },
    ],
    reconnectCount: 0,
    messagesReceived: 0,
    lastLatencyMs: null,
  });
  const [uptimeMs, setUptimeMs] = useState(0);

  const handlersRef = useRef(handlers);
  useEffect(() => {
    handlersRef.current = handlers;
  }, [handlers]);

  const updateChannel = useCallback((name: string, connected: boolean) => {
    setState((prev) => {
      const updated = prev.channels.map((ch) =>
        ch.name === name ? { ...ch, connected } : ch,
      );
      const reconnectDelta = !connected ? 1 : 0;
      return {
        ...prev,
        channels: updated,
        reconnectCount: prev.reconnectCount + reconnectDelta,
      };
    });
  }, []);

  const incrementMessages = useCallback(() => {
    setState((prev) => ({
      ...prev,
      messagesReceived: prev.messagesReceived + 1,
    }));
  }, []);

  useEffect(() => {
    const marketCh = createRealtimeChannel({ channel: "market", symbol });
    const signalsCh = createRealtimeChannel({ channel: "signals", symbol });
    const portfolioCh = createRealtimeChannel({ channel: "portfolio" });
    const metricsCh = createRealtimeChannel({ channel: "metrics" });

    const unsubs = [
      marketCh.subscribe((data) => {
        incrementMessages();
        handlersRef.current.onMarket?.(data);
      }),
      signalsCh.subscribe((data) => {
        incrementMessages();
        handlersRef.current.onSignal?.(data);
      }),
      portfolioCh.subscribe((data) => {
        incrementMessages();
        handlersRef.current.onPortfolio?.(data);
      }),
      metricsCh.subscribe((data) => {
        incrementMessages();
        handlersRef.current.onMetrics?.(data);
      }),
      marketCh.subscribeStatus((connected) =>
        updateChannel("market", connected),
      ),
      signalsCh.subscribeStatus((connected) =>
        updateChannel("signals", connected),
      ),
      portfolioCh.subscribeStatus((connected) =>
        updateChannel("portfolio", connected),
      ),
      metricsCh.subscribeStatus((connected) =>
        updateChannel("metrics", connected),
      ),
    ];

    marketCh.start();
    signalsCh.start();
    portfolioCh.start();
    metricsCh.start();

    const uptimeTimer = window.setInterval(() => {
      setUptimeMs((prev) => prev + 1000);
    }, 1000);

    return () => {
      unsubs.forEach((u) => u());
      marketCh.stop();
      signalsCh.stop();
      portfolioCh.stop();
      metricsCh.stop();
      window.clearInterval(uptimeTimer);
    };
  }, [symbol, updateChannel, incrementMessages]);

  // Uptime calculation
  const uptime = formatUptime(uptimeMs);

  return {
    ...state,
    uptime,
  };
}

function formatUptime(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  const h = Math.floor(m / 60);
  const mins = m % 60;
  if (h > 0) return `${h}h ${mins}m`;
  if (mins > 0) return `${mins}m ${s}s`;
  return `${s}s`;
}
