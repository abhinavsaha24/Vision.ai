import React, { useEffect, useRef } from "react";
import { createChart } from "lightweight-charts";

/**
 * Volume.js — Volume histogram chart
 * Fixed: proper chart disposal on unmount, correct layout config
 */

function Volume({ data = [] }) {
  const ref = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);

  // Create chart once
  useEffect(() => {
    if (!ref.current) return;

    const chart = createChart(ref.current, {
      height: 120,
      layout: {
        background: { color: "#0b0b0b" },
        textColor: "#DDE",
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { color: "#18202A" },
      },
      rightPriceScale: { visible: false },
      timeScale: { visible: false },
    });

    const hist = chart.addHistogramSeries({
      color: "#26a69a",
      priceFormat: { type: "volume" },
      priceScaleId: "",
    });

    chartRef.current = chart;
    seriesRef.current = hist;

    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  // Update data when it changes
  useEffect(() => {
    if (!seriesRef.current || !data.length) return;

    // Sort ascending by time
    const sorted = [...data].sort((a, b) => a.time - b.time);
    seriesRef.current.setData(sorted);
  }, [data]);

  return (
    <div>
      <div className="card-title">Volume</div>
      <div ref={ref} style={{ width: "100%", height: "120px" }} />
    </div>
  );
}

export default Volume;