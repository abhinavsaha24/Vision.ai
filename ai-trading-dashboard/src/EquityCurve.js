import React, { useEffect, useRef } from "react";
import { createChart } from "lightweight-charts";

function EquityCurve({ portfolio }) {

const ref = useRef(null);

useEffect(() => {

if (!ref.current) return;

const chart = createChart(ref.current, {
height: 200,
layout: {
background: { color: "#0f0f0f" },
textColor: "#DDD"
},
grid: {
vertLines: { color: "#1a1a1a" },
horzLines: { color: "#1a1a1a" }
}
});

const lineSeries = chart.addLineSeries({
color: "#00ff9c",
lineWidth: 2
});

if (portfolio?.history) {

const data = portfolio.history.map((v, i) => ({
time: i,
value: v
}));

lineSeries.setData(data);

}

return () => {
chart.remove();
};

}, [portfolio]);

return <div ref={ref} style={{ width: "100%" }}></div>;

}

export default EquityCurve;