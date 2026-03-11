import React, { useEffect, useRef } from "react";
import { createChart } from "lightweight-charts";

function Chart({ symbol = "BTCUSDT", predictions = [] }) {

  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  const wsRef = useRef(null);

  useEffect(() => {

    if (!containerRef.current) return;

    // Create chart
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 420,
      layout: {
        background: { color: "#0b0b0b" },
        textColor: "#DDE"
      },
      grid: {
        vertLines: { color: "#18202A" },
        horzLines: { color: "#18202A" }
      },
      crosshair: {
        mode: 1
      },
      rightPriceScale: {
        borderColor: "#333"
      },
      timeScale: {
        borderColor: "#333"
      }
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderVisible: false,
      wickUpColor: "#26a69a",
      wickDownColor: "#ef5350"
    });

    chartRef.current = chart;
    seriesRef.current = candleSeries;

    // ------------------------------
    // Load historical candles first
    // ------------------------------

    const loadHistory = async () => {

      try {

        const res = await fetch(
          `https://api.binance.com/api/v3/klines?symbol=${symbol}&interval=5m&limit=200`
        );

        const data = await res.json();

        const candles = data.map(c => ({
          time: c[0] / 1000,
          open: parseFloat(c[1]),
          high: parseFloat(c[2]),
          low: parseFloat(c[3]),
          close: parseFloat(c[4])
        }));

        candleSeries.setData(candles);

      } catch (err) {
        console.error("Failed to load history", err);
      }
    };

    loadHistory();

    // ------------------------------
    // WebSocket connection
    // ------------------------------

    const connectWS = () => {

      const pair = symbol.toLowerCase();

      const ws = new WebSocket(
        `wss://stream.binance.com:9443/ws/${pair}@kline_5m`
      );

      wsRef.current = ws;

      ws.onmessage = (event) => {

        try {

          const msg = JSON.parse(event.data);
          const k = msg.k;

          const candle = {
            time: k.t / 1000,
            open: parseFloat(k.o),
            high: parseFloat(k.h),
            low: parseFloat(k.l),
            close: parseFloat(k.c)
          };

          candleSeries.update(candle);

        } catch (err) {
          console.error("WebSocket parse error", err);
        }
      };

      ws.onerror = (err) => {
        console.warn("Chart websocket error", err);
      };

      ws.onclose = () => {

        console.warn("Chart websocket closed. Reconnecting...");

        setTimeout(connectWS, 3000);
      };
    };

    connectWS();

    // ------------------------------
    // Prediction markers
    // ------------------------------

    if (predictions && predictions.length > 0) {

      const markers = predictions.map((p, i) => ({

        time: Math.floor(Date.now() / 1000) - i * 60,

        position: p.direction === "UP"
          ? "belowBar"
          : "aboveBar",

        color: p.direction === "UP"
          ? "#00ff9c"
          : "#ff4d4d",

        shape: p.direction === "UP"
          ? "arrowUp"
          : "arrowDown",

        text: `${Math.round(p.probability * 100)}%`

      }));

      candleSeries.setMarkers(markers);
    }

    // ------------------------------
    // Responsive resize
    // ------------------------------

    const handleResize = () => {

      if (containerRef.current && chartRef.current) {

        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth
        });

      }
    };

    window.addEventListener("resize", handleResize);

    // ------------------------------
    // Cleanup
    // ------------------------------

    return () => {

      if (wsRef.current) wsRef.current.close();

      window.removeEventListener("resize", handleResize);

      chart.remove();

    };

  }, [symbol, predictions]);

  return (
    <div
      ref={containerRef}
      style={{
        width: "100%",
        height: "420px"
      }}
    />
  );
}

export default Chart;