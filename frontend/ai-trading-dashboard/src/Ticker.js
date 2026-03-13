import React, { useEffect, useRef } from "react";
import { createChart, CandlestickSeries } from "lightweight-charts";

function Chart({ predictions, symbol }) {

  const chartContainerRef = useRef(null);

  useEffect(() => {

    if (!chartContainerRef.current) return;

    chartContainerRef.current.innerHTML = "";

    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: 400,

      layout: {
        background: { color: "#0f0f0f" },
        textColor: "#DDD"
      },

      grid: {
        vertLines: { color: "#222" },
        horzLines: { color: "#222" }
      },

      timeScale: {
        borderColor: "#333",
        timeVisible: true
      },

      rightPriceScale: {
        borderColor: "#333"
      }
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderUpColor: "#26a69a",
      borderDownColor: "#ef5350",
      wickUpColor: "#26a69a",
      wickDownColor: "#ef5350"
    });

    const loadData = async () => {

      try {

        const pair =
          symbol === "ETH-USD"
            ? "ETHUSDT"
            : "BTCUSDT";

        const res = await fetch(
          `https://api.binance.com/api/v3/klines?symbol=${pair}&interval=5m&limit=120`
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

        if (predictions && predictions.length > 0) {

          const markers = predictions.map((p, i) => ({
            time: candles[candles.length - 1 - i].time,
            position: p.direction === "UP" ? "belowBar" : "aboveBar",
            color: p.direction === "UP" ? "#26a69a" : "#ef5350",
            shape: p.direction === "UP" ? "arrowUp" : "arrowDown",
            text: p.direction
          }));

          candleSeries.setMarkers(markers);

        }

      } catch (err) {
        console.error("Chart error:", err);
      }

    };

    loadData();

    const interval = setInterval(loadData, 60000);

    const handleResize = () => {
      chart.applyOptions({
        width: chartContainerRef.current.clientWidth
      });
    };

    window.addEventListener("resize", handleResize);

    return () => {
      clearInterval(interval);
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };

  }, [predictions, symbol]);

  return (
    <div
      ref={chartContainerRef}
      style={{
        width: "100%",
        background: "#0f0f0f",
        borderRadius: "8px"
      }}
    />
  );
}

export default Chart;