"use client";

import React, { useEffect, useRef } from "react";
import { createChart, IChartApi, ISeriesApi, ColorType, CandlestickSeries, HistogramSeries } from "lightweight-charts";
import { useMarketStore } from "@/store/marketStore";
import { useSignalStore } from "@/store/signalStore";

export function TVChart() {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candlestickSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);

  const { liveKline, historicalData } = useMarketStore();
  const { prediction } = useSignalStore();

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#94a3b8', // slate-400
      },
      grid: {
        vertLines: { color: '#1e293b' }, // slate-800
        horzLines: { color: '#1e293b' },
      },
      crosshair: {
        mode: 0, // Normal
      },
      rightPriceScale: {
        borderColor: '#1e293b',
      },
      timeScale: {
        borderColor: '#1e293b',
        timeVisible: true,
        secondsVisible: false,
      },
      autoSize: true,
    });

    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981', // emerald-500
      downColor: '#f43f5e', // rose-500
      borderVisible: false,
      wickUpColor: '#10b981',
      wickDownColor: '#f43f5e',
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: '#3b82f6',
      priceFormat: { type: 'volume' },
      priceScaleId: '', // set as an overlay
    });

    chart.priceScale('').applyOptions({
      scaleMargins: {
        top: 0.8,
        bottom: 0,
      },
    });

    chartRef.current = chart;
    candlestickSeriesRef.current = candlestickSeries;
    volumeSeriesRef.current = volumeSeries;

    if (historicalData && historicalData.length > 0) {
      // lightweight-charts needs time in seconds or string format
      candlestickSeries.setData(historicalData as any);
      const volumeData = historicalData.map(d => ({
        time: d.time,
        value: d.volume,
        color: d.close >= d.open ? '#059669' : '#e11d48' // slightly darker colors for volume
      }));
      volumeSeries.setData(volumeData as any);
    }

    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, []); // Only initialization

  // Update real-time 
  useEffect(() => {
    if (candlestickSeriesRef.current && volumeSeriesRef.current && liveKline) {
      // lightweight-charts needs time in seconds or string format
      candlestickSeriesRef.current.update(liveKline as any);
      
      volumeSeriesRef.current.update({
        time: liveKline.time,
        value: liveKline.volume,
        color: liveKline.close >= liveKline.open ? '#059669' : '#e11d48'
      } as any);
    }
  }, [liveKline]);

  // Handle Signal Markers
  useEffect(() => {
    if (candlestickSeriesRef.current && prediction) {
      const latestTime = liveKline?.time || (historicalData.length > 0 ? historicalData[historicalData.length - 1].time : null);
      if (latestTime && (prediction.signal === 'BUY' || prediction.signal === 'SELL')) {
        (candlestickSeriesRef.current as any).setMarkers([
          {
            time: latestTime as any,
            position: prediction.signal === 'BUY' ? 'belowBar' : 'aboveBar',
            color: prediction.signal === 'BUY' ? '#10b981' : '#f43f5e',
            shape: prediction.signal === 'BUY' ? 'arrowUp' : 'arrowDown',
            text: prediction.signal,
          }
        ]);
      } else {
        (candlestickSeriesRef.current as any).setMarkers([]);
      }
    }
  }, [prediction, liveKline, historicalData]);

  return (
    <div className="w-full h-full min-h-[400px] flex flex-col rounded-xl border border-slate-800 bg-slate-900/50 backdrop-blur-xl overflow-hidden shadow">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 bg-slate-900/80">
        <h3 className="font-semibold text-slate-100">BTC/USDT</h3>
        <span className="text-xs font-medium text-emerald-400 bg-emerald-500/10 px-2 py-1 rounded">Live</span>
      </div>
      <div ref={chartContainerRef} className="flex-1 w-full relative" />
    </div>
  );
}
