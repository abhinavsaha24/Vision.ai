// src/Volume.js
import React, { useEffect, useRef } from "react";
import { createChart } from "lightweight-charts";

function Volume({ data = [] }) {
  const ref = useRef();

  useEffect(() => {
    if (!ref.current) return;

    const chart = createChart(ref.current, {
      height: 120,
      layout: { backgroundColor: "#0b0b0b", textColor: "#DDE" }
    });

    const hist = chart.addHistogramSeries({
      color: '#26a69a',
      priceFormat: { type: 'volume' },
      priceScaleId: '',
      scaleMargins: { top: 0.8, bottom: 0 }
    });

    hist.setData(data);

    return () => chart.remove();
  }, [data]);

  return <div ref={ref} />;
}

export default Volume;