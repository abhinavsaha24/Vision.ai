import React from "react";

function RiskPanel() {
  return (
    <div>
      <div className="card-title">Risk Controls</div>
      <div className="space-y">
        <div className="row-between">
          <span className="metric-label">Max Position</span>
          <span className="text-cyan" style={{ fontFamily: "'JetBrains Mono'" }}>5%</span>
        </div>
        <div className="row-between">
          <span className="metric-label">Max Drawdown</span>
          <span className="text-orange" style={{ fontFamily: "'JetBrains Mono'" }}>20%</span>
        </div>
        <div className="row-between">
          <span className="metric-label">Max Daily Loss</span>
          <span className="text-red" style={{ fontFamily: "'JetBrains Mono'" }}>5%</span>
        </div>
        <div className="row-between">
          <span className="metric-label">Max Open Trades</span>
          <span className="text-purple" style={{ fontFamily: "'JetBrains Mono'" }}>5</span>
        </div>
        <div className="row-between">
          <span className="metric-label">Stop Loss</span>
          <span className="text-dim" style={{ fontFamily: "'JetBrains Mono'" }}>ATR-Based</span>
        </div>
        <div className="row-between">
          <span className="metric-label">Trailing Stop</span>
          <span className="text-green" style={{ fontFamily: "'JetBrains Mono'" }}>Active</span>
        </div>
      </div>
    </div>
  );
}

export default RiskPanel;