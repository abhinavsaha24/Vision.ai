import React, { useEffect, useRef, useCallback } from "react";
import { createChart } from "lightweight-charts";

/**
 * Chart.js — Live candlestick chart with integrated volume histogram
 *
 * Features:
 *  - Candlestick + volume in a single chart
 *  - Green/red volume bars based on close vs open
 *  - Real-time WebSocket updates for both price and volume
 *  - Exponential backoff reconnect + stale connection detection
 *  - Proper React lifecycle disposal
 */

const WS_BASE = "wss://stream.binance.com/ws";
const MAX_RECONNECT_DELAY = 30000;
const STALE_TIMEOUT = 60000;

function Chart({ symbol = "BTCUSDT", predictions = [] }) {

  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const volumeSeriesRef = useRef(null);
  const wsRef = useRef(null);
  const reconnectRef = useRef(null);
  const attemptRef = useRef(0);
  const lastMessageRef = useRef(Date.now());
  const staleTimerRef = useRef(null);
  const disposed = useRef(false);

  // ----------------------------------
  // Create chart once with both series
  // ----------------------------------

  useEffect(() => {
    if (!containerRef.current) return;

    disposed.current = false;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 480,
      layout: {
        background: { color: "#0a0a0f" },
        textColor: "#8888a0",
        fontFamily: "'Inter', sans-serif",
      },
      grid: {
        vertLines: { color: "rgba(42, 42, 58, 0.3)" },
        horzLines: { color: "rgba(42, 42, 58, 0.3)" },
      },
      crosshair: {
        mode: 0,
        vertLine: { color: "rgba(74, 158, 255, 0.3)", width: 1, style: 2 },
        horzLine: { color: "rgba(74, 158, 255, 0.3)", width: 1, style: 2 },
      },
      rightPriceScale: {
        borderColor: "rgba(42, 42, 58, 0.5)",
        scaleMargins: { top: 0.05, bottom: 0.25 },
      },
      timeScale: {
        borderColor: "rgba(42, 42, 58, 0.5)",
        timeVisible: true,
        secondsVisible: false,
      },
    });

    // Candlestick series
    const candleSeries = chart.addCandlestickSeries({
      upColor: "#00e676",
      downColor: "#ff4757",
      borderVisible: false,
      wickUpColor: "#00e676",
      wickDownColor: "#ff4757",
    });

    // Volume histogram series (overlaid at bottom)
    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });

    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;

    const resize = () => {
      if (disposed.current || !containerRef.current || !chartRef.current) return;
      chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
    };

    window.addEventListener("resize", resize);

    return () => {
      disposed.current = true;
      window.removeEventListener("resize", resize);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ----------------------------------
  // Load historical candles + volume
  // ----------------------------------

  useEffect(() => {
    if (!candleSeriesRef.current || disposed.current) return;

    let cancelled = false;

    const loadHistory = async () => {
      try {
        const res = await fetch(
          `https://api.binance.com/api/v3/klines?symbol=${symbol}&interval=5m&limit=300`
        );
        const data = await res.json();

        if (cancelled || disposed.current || !candleSeriesRef.current) return;

        const candles = [];
        const volumes = [];

        data.forEach((c) => {
          const time = Math.floor(c[0] / 1000);
          const open = parseFloat(c[1]);
          const high = parseFloat(c[2]);
          const low = parseFloat(c[3]);
          const close = parseFloat(c[4]);
          const vol = parseFloat(c[5]);

          candles.push({ time, open, high, low, close });
          volumes.push({
            time,
            value: vol,
            color: close >= open
              ? "rgba(0, 230, 118, 0.35)"   // green (buy)
              : "rgba(255, 71, 87, 0.35)",   // red (sell)
          });
        });

        // Sort ascending + deduplicate
        candles.sort((a, b) => a.time - b.time);
        volumes.sort((a, b) => a.time - b.time);

        const seenC = new Set();
        const uniqueCandles = candles.filter((c) => {
          if (seenC.has(c.time)) return false;
          seenC.add(c.time);
          return true;
        });

        const seenV = new Set();
        const uniqueVolumes = volumes.filter((v) => {
          if (seenV.has(v.time)) return false;
          seenV.add(v.time);
          return true;
        });

        candleSeriesRef.current.setData(uniqueCandles);
        if (volumeSeriesRef.current) {
          volumeSeriesRef.current.setData(uniqueVolumes);
        }
      } catch (err) {
        console.error("Failed to load history", err);
      }
    };

    loadHistory();

    return () => { cancelled = true; };
  }, [symbol]);

  // ----------------------------------
  // WebSocket with exponential backoff
  // ----------------------------------

  const connectWS = useCallback(() => {
    if (disposed.current) return;

    if (wsRef.current) {
      try { wsRef.current.close(); } catch {}
    }

    const pair = symbol.toLowerCase();
    const ws = new WebSocket(`${WS_BASE}/${pair}@kline_5m`);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("Chart WS connected");
      attemptRef.current = 0;
      lastMessageRef.current = Date.now();
    };

    ws.onmessage = (event) => {
      if (disposed.current || !candleSeriesRef.current) return;
      lastMessageRef.current = Date.now();

      try {
        const msg = JSON.parse(event.data);
        const k = msg.k;
        if (!k) return;

        const time = Math.floor(k.t / 1000);
        const open = parseFloat(k.o);
        const high = parseFloat(k.h);
        const low = parseFloat(k.l);
        const close = parseFloat(k.c);
        const vol = parseFloat(k.v);

        // Update candle
        candleSeriesRef.current.update({ time, open, high, low, close });

        // Update volume
        if (volumeSeriesRef.current) {
          volumeSeriesRef.current.update({
            time,
            value: vol,
            color: close >= open
              ? "rgba(0, 230, 118, 0.35)"
              : "rgba(255, 71, 87, 0.35)",
          });
        }
      } catch (err) {
        console.error("WS parse error", err);
      }
    };

    ws.onerror = (err) => {
      console.warn("Chart WS error", err);
    };

    ws.onclose = () => {
      if (disposed.current) return;

      const delay = Math.min(1000 * Math.pow(2, attemptRef.current), MAX_RECONNECT_DELAY);
      attemptRef.current += 1;
      console.warn(`Chart WS closed — reconnecting in ${delay}ms (attempt ${attemptRef.current})`);

      reconnectRef.current = setTimeout(() => {
        if (!disposed.current) connectWS();
      }, delay);
    };
  }, [symbol]);

  // Stale connection detector
  useEffect(() => {
    staleTimerRef.current = setInterval(() => {
      if (disposed.current) return;
      if (Date.now() - lastMessageRef.current > STALE_TIMEOUT && wsRef.current) {
        console.warn("Chart WS stale — forcing reconnect");
        wsRef.current.close();
      }
    }, STALE_TIMEOUT / 2);

    return () => clearInterval(staleTimerRef.current);
  }, []);

  // Connect on mount / symbol change
  useEffect(() => {
    connectWS();

    return () => {
      if (wsRef.current) { try { wsRef.current.close(); } catch {} }
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
    };
  }, [connectWS]);

  // ----------------------------------
  // Prediction markers
  // ----------------------------------

  useEffect(() => {
    if (disposed.current || !candleSeriesRef.current) return;
    if (!predictions || predictions.length === 0) return;

    const now = Math.floor(Date.now() / 1000);

    const markers = predictions.map((p, i) => ({
      time: now - i * 300,
      position: p.direction === "UP" ? "belowBar" : "aboveBar",
      color: p.direction === "UP" ? "#00e676" : "#ff4757",
      shape: p.direction === "UP" ? "arrowUp" : "arrowDown",
      text: `${Math.round(p.probability * 100)}%`,
    }));

    markers.sort((a, b) => a.time - b.time);

    try {
      candleSeriesRef.current.setMarkers(markers);
    } catch {}
  }, [predictions]);

  return (
    <div
      ref={containerRef}
      style={{ width: "100%", height: "480px" }}
    />
  );
}

export default Chart;