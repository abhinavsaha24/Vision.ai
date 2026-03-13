import React from "react";

function RiskDashboard({ riskData }) {
  if (!riskData) {
    return (
      <div>
        <div className="card-title">Risk Dashboard</div>
        <div className="text-dim" style={{ fontSize: "0.8rem" }}>Loading risk data...</div>
      </div>
    );
  }

  const level = riskData.risk_level || "unknown";
  const colorClass = level === "high" ? "text-red" : level === "medium" ? "text-orange" : "text-green";
  const tagColor = level === "high" ? "red" : level === "medium" ? "orange" : "green";

  return (
    <div>
      <div className="card-title">Risk Dashboard</div>

      <div style={{ textAlign: "center", marginBottom: 12 }}>
        <span className={`tag tag-${tagColor}`} style={{ fontSize: "0.8rem", padding: "6px 16px" }}>
          {level.toUpperCase()}
        </span>
      </div>

      <div className="space-y">
        <div className="row-between">
          <span className="metric-label">Risk Score</span>
          <span className={colorClass} style={{ fontFamily: "'JetBrains Mono'" }}>
            {riskData.risk_score?.toFixed(4) || "--"}
          </span>
        </div>

        {riskData.factors && Object.entries(riskData.factors).map(([key, val]) => (
          <div className="row-between" key={key}>
            <span className="metric-label">{key.replace(/_/g, " ")}</span>
            <span className="text-dim" style={{ fontFamily: "'JetBrains Mono'", fontSize: "0.75rem" }}>
              {typeof val === "number" ? val.toFixed(4) : String(val)}
            </span>
          </div>
        ))}
      </div>

      {riskData.kill_switch && (
        <div style={{ textAlign: "center", marginTop: 12, padding: 8, background: "rgba(255,71,87,0.1)", borderRadius: 8 }}>
          <span className="text-red" style={{ fontWeight: 700, fontSize: "0.85rem" }}>
            ⚠ KILL SWITCH ACTIVE
          </span>
        </div>
      )}
    </div>
  );
}

export default RiskDashboard;