import React, { useEffect, useRef } from "react";
import { createChart, LineSeries } from "lightweight-charts";

function EquityCurve({ portfolio, price }) {

  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  const historyRef = useRef([]);

  useEffect(() => {

    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {

      width: containerRef.current.clientWidth,
      height: 200,

      layout:{
        background:{ color:"#0f0f0f" },
        textColor:"#DDD"
      },

      grid:{
        vertLines:{ color:"#222" },
        horzLines:{ color:"#222" }
      },

      timeScale:{
        timeVisible:true,
        secondsVisible:true
      }

    });

    const lineSeries = chart.addSeries(LineSeries,{
      color:"#00ff9c",
      lineWidth:2
    });

    chartRef.current = chart;
    seriesRef.current = lineSeries;

    const handleResize = () => {
      chart.applyOptions({
        width: containerRef.current.clientWidth
      });
    };

    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };

  }, []);

  /* ---------- UPDATE EQUITY ---------- */

  useEffect(() => {

    if(!portfolio || !price || !seriesRef.current) return;

    const equity = portfolio.cash + portfolio.btc * price;

    const point = {
      time: Math.floor(Date.now()/1000),
      value: equity
    };

    historyRef.current.push(point);

    seriesRef.current.setData(historyRef.current);

  }, [portfolio, price]);

  return (
    <div
      ref={containerRef}
      style={{ width:"100%", marginTop:20 }}
    />
  );

}

export default EquityCurve;