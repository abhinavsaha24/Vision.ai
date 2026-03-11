// src/Chart.js
import React, { useEffect, useRef } from "react";
import { createChart } from "lightweight-charts";

function Chart({ symbol, predictions }) {
  const ref = useRef();

  useEffect(() => {
    if (!ref.current) return;

    const chart = createChart(ref.current, {
      width: ref.current.clientWidth,
      height: 420,
      layout: {
        backgroundColor: "#0b0b0b",
        textColor: "#DDE"
      },
      grid: {
        vertLines: { color: "#18202A" },
        horzLines: { color: "#18202A" }
      },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderVisible: false
    });

    // dummy or real initial data
    candleSeries.setData([]);

    // Optional: overlay prediction markers (convert predictions to markers)
    const markers = (predictions || []).map((p, idx) => ({
      time: Math.floor(Date.now() / 1000) - idx * 60,
      position: p.direction === "UP" ? "aboveBar" : "belowBar",
      color: p.direction === "UP" ? "#00ff9c" : "#ff4d4d",
      shape: "arrowUp",
      text: `${Math.round(p.probability*100)}%`
    }));
    if (markers.length) candleSeries.setMarkers(markers);

    // WebSocket for real-time kline
    const pair = (symbol || "BTCUSDT").toLowerCase();
    const ws = new WebSocket(`wss://stream.binance.com:9443/ws/${pair}@kline_5m`);

    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        const k = data.k;
        const point = {
          time: Math.floor(k.t / 1000),
          open: parseFloat(k.o),
          high: parseFloat(k.h),
          low: parseFloat(k.l),
          close: parseFloat(k.c)
        };
        candleSeries.update(point);
      } catch (e) {
        console.error("Chart websocket message parse error", e);
      }
    };

    ws.onerror = (e) => console.warn("Chart websocket error:", e);
    ws.onclose = () => console.info("Chart websocket closed");

    const resize = () => {
      chart.applyOptions({ width: ref.current.clientWidth });
    };
    window.addEventListener("resize", resize);

    return () => {
      ws.close();
      window.removeEventListener("resize", resize);
      chart.remove();
    };
  }, [symbol, predictions]);

  return <div ref={ref} style={{ width: "100%" }} />;
}

export default Chart;