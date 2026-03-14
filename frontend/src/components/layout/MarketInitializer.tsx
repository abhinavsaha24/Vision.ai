"use client";

import { useEffect } from "react";
import { useMarketStore } from "@/store/marketStore";

export function MarketInitializer() {
  const { startWebSocket, stopWebSocket } = useMarketStore();

  useEffect(() => {
    // Start the Binance WebSocket globally when the app mounts
    startWebSocket();

    return () => {
      // Clean up connection when the app unmounts
      stopWebSocket();
    };
  }, [startWebSocket, stopWebSocket]);

  return null; // This is a logic-only component, it renders nothing
}
