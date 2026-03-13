import React from "react";

function MarketTimeline() {
  const events = [
    { time: "Now", event: "AI model running", status: "active" },
    { time: "Every 30s", event: "Price refresh", status: "active" },
    { time: "Every 60s", event: "News + sentiment update", status: "active" },
    { time: "On demand", event: "Model retraining", status: "idle" },
    { time: "On demand", event: "Backtesting", status: "idle" },
  ];

  return (
    <div>
      <div className="card-title">System Timeline</div>
      <div className="space-y">
        {events.map((e, i) => (
          <div key={i} className="row-between" style={{ padding: "3px 0" }}>
            <div>
              <span style={{ fontSize: "0.75rem", color: "var(--text-secondary)" }}>{e.time}</span>
              <span style={{ fontSize: "0.78rem", marginLeft: 8 }}>{e.event}</span>
            </div>
            <span className={`tag tag-${e.status === "active" ? "green" : "blue"}`}>
              {e.status}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default MarketTimeline;