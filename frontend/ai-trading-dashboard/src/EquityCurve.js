import React from "react";
import { Line } from "react-chartjs-2";
import {
  Chart as ChartJS,
  LineElement,
  PointElement,
  LinearScale,
  CategoryScale,
  Filler,
  Tooltip,
} from "chart.js";

ChartJS.register(LineElement, PointElement, LinearScale, CategoryScale, Filler, Tooltip);

function EquityCurve({ portfolio, price }) {
  const equity = portfolio?.equity_curve || portfolio?.history?.map(t => t.equity) || [];

  if (equity.length < 2) {
    return <div className="text-dim" style={{ fontSize: "0.8rem" }}>Not enough data</div>;
  }

  const data = {
    labels: equity.map((_, i) => `${i}`),
    datasets: [
      {
        label: "Equity",
        data: equity.slice(-50),
        borderColor: "#4a9eff",
        backgroundColor: "rgba(74,158,255,0.08)",
        borderWidth: 2,
        tension: 0.4,
        fill: true,
        pointRadius: 0,
      },
    ],
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false }, tooltip: { mode: "index" } },
    scales: {
      x: { display: false },
      y: {
        grid: { color: "rgba(42,42,58,0.3)" },
        ticks: { color: "#8888a0", font: { size: 10, family: "'JetBrains Mono'" } },
      },
    },
  };

  return (
    <div style={{ height: 150 }}>
      <Line data={data} options={options} />
    </div>
  );
}

export default EquityCurve;