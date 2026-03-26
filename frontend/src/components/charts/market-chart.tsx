"use client";

import { useEffect, useMemo, useRef } from "react";
import { ColorType, createChart, type IChartApi } from "lightweight-charts";
import { Kline } from "@/services/api";
import { useMarketStore } from "@/store/marketStore";

function ema(values: number[], period: number): number[] {
  if (!values.length) return [];
  const k = 2 / (period + 1);
  const out: number[] = [values[0]];
  for (let i = 1; i < values.length; i++) {
    out.push(values[i] * k + out[i - 1] * (1 - k));
  }
  return out;
}

export function MarketChart({
  candles,
  markers,
}: {
  candles: Kline[];
  markers: Array<{
    time: number;
    position: "aboveBar" | "belowBar";
    color: string;
    text: string;
  }>;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const market = useMarketStore((state) => state.market);

  const disposeChart = () => {
    if (!chartRef.current) return;
    try {
      chartRef.current.remove();
    } catch {
      // Ignore cases where chart was already disposed during rapid remounts.
    } finally {
      chartRef.current = null;
    }
  };

  const priceSeriesData = useMemo(
    () =>
      candles.map((k) => ({
        time: k.time as never,
        open: k.open,
        high: k.high,
        low: k.low,
        close: k.close,
      })),
    [candles],
  );

  const volumeSeriesData = useMemo(
    () =>
      candles.map((k) => ({
        time: k.time as never,
        value: k.volume,
        color:
          k.close >= k.open ? "rgba(16,185,129,0.35)" : "rgba(244,63,94,0.35)",
      })),
    [candles],
  );

  useEffect(() => {
    if (!containerRef.current) return;
    if (
      containerRef.current.clientWidth <= 0 ||
      containerRef.current.clientHeight <= 0
    ) {
      return;
    }

    disposeChart();

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#020617" },
        textColor: "#94a3b8",
      },
      rightPriceScale: { borderColor: "rgba(148,163,184,0.2)" },
      timeScale: { borderColor: "rgba(148,163,184,0.2)" },
      grid: {
        vertLines: { color: "rgba(148,163,184,0.08)" },
        horzLines: { color: "rgba(148,163,184,0.08)" },
      },
      localization: { locale: "en-US" },
      crosshair: { mode: 1 },
    });

    const candlesSeries = chart.addCandlestickSeries({
      upColor: "#10b981",
      downColor: "#f43f5e",
      borderUpColor: "#10b981",
      borderDownColor: "#f43f5e",
      wickUpColor: "#10b981",
      wickDownColor: "#f43f5e",
    });

    const emaFast = chart.addLineSeries({
      color: "#22d3ee",
      lineWidth: 2,
      title: "EMA 12",
    });

    const emaSlow = chart.addLineSeries({
      color: "#f59e0b",
      lineWidth: 2,
      title: "EMA 26",
    });

    const volume = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "",
    });

    volume.priceScale().applyOptions({
      scaleMargins: {
        top: 0.8,
        bottom: 0,
      },
    });

    candlesSeries.setData(priceSeriesData);
    volume.setData(volumeSeriesData);

    const closes = candles.map((c) => c.close);
    const ema12 = ema(closes, 12);
    const ema26 = ema(closes, 26);

    emaFast.setData(
      candles.map((c, i) => ({ time: c.time as never, value: ema12[i] })),
    );
    emaSlow.setData(
      candles.map((c, i) => ({ time: c.time as never, value: ema26[i] })),
    );

    candlesSeries.setMarkers(markers as never);

    chart.timeScale().fitContent();

    const resizeObserver = new ResizeObserver(() => {
      if (!containerRef.current) return;
      chart.applyOptions({
        width: containerRef.current.clientWidth,
        height: containerRef.current.clientHeight,
      });
    });
    resizeObserver.observe(containerRef.current);

    chartRef.current = chart;

    return () => {
      resizeObserver.disconnect();
      if (chartRef.current === chart) {
        disposeChart();
      } else {
        try {
          chart.remove();
        } catch {
          // No-op if a newer render already disposed this instance.
        }
      }
    };
  }, [candles, markers, priceSeriesData, volumeSeriesData]);

  return (
    <div className="relative h-115 min-h-90 w-full rounded-xl border border-white/10 bg-slate-950/70">
      <div ref={containerRef} className="h-full w-full" />
      {market?.stale ? (
        <div className="absolute right-4 top-4 rounded-full border border-amber-500/50 bg-amber-500/10 px-3 py-1 text-xs text-amber-300">
          Market snapshot stale
        </div>
      ) : null}
    </div>
  );
}
