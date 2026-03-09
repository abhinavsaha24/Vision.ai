import React, { useEffect, useRef } from "react";
import {
  createChart,
  CandlestickSeries,
  createSeriesMarkers
} from "lightweight-charts";

function Chart({ predictions, symbol }) {

  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  const socketRef = useRef(null);

  const symbolMap = {
    "BTC-USD": "BTCUSDT",
    "ETH-USD": "ETHUSDT",
    "SOL-USD": "SOLUSDT"
  };

  useEffect(() => {

    if (!containerRef.current) return;

    const pair = symbolMap[symbol] || "BTCUSDT";

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 420,

      layout:{
        background:{ color:"#0f0f0f" },
        textColor:"#DDD"
      },

      grid:{
        vertLines:{ color:"#1d1d1d" },
        horzLines:{ color:"#1d1d1d" }
      }
    });

    const candleSeries = chart.addSeries(CandlestickSeries,{
      upColor:"#26a69a",
      downColor:"#ef5350",
      borderUpColor:"#26a69a",
      borderDownColor:"#ef5350",
      wickUpColor:"#26a69a",
      wickDownColor:"#ef5350"
    });

    chartRef.current = chart;
    seriesRef.current = candleSeries;

    /* ---------- LOAD HISTORICAL DATA ---------- */

    const loadData = async () => {

      const res = await fetch(
        `https://api.binance.com/api/v3/klines?symbol=${pair}&interval=5m&limit=200`
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

      /* AI markers */

      if(predictions && predictions.length > 0){

        const markers = predictions.map(p=>({

          time:candles[candles.length-1].time,

          position:p.direction==="UP"
            ?"belowBar":"aboveBar",

          color:p.direction==="UP"
            ?" #00ff9c":"#ff4d4d",

          shape:p.direction==="UP"
            ?"arrowUp":"arrowDown",

          text:p.direction==="UP"
            ?"BUY":"SELL"

        }));

        createSeriesMarkers(candleSeries,markers);

      }

    };

    loadData();

    /* ---------- LIVE STREAM ---------- */

    const ws = new WebSocket(
      `wss://stream.binance.com:9443/ws/${pair.toLowerCase()}@kline_5m`
    );

    socketRef.current = ws;

    ws.onmessage = (event)=>{

      const msg = JSON.parse(event.data);
      const k = msg.k;

      const candle = {
        time:k.t/1000,
        open:parseFloat(k.o),
        high:parseFloat(k.h),
        low:parseFloat(k.l),
        close:parseFloat(k.c)
      };

      seriesRef.current.update(candle);

    };

    return ()=>{
      ws.close();
      chart.remove();
    };

  },[symbol,predictions]);

  return <div ref={containerRef} style={{width:"100%"}}/>;

}

export default Chart;