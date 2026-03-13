import React from "react";

function PnLDashboard({ portfolio, price }) {
  if (!portfolio) return null;

  const cash = portfolio.cash || 0;
  const btc = portfolio.btc || 0;
  const totalValue = cash + (btc * (price || 0));
  const initialCapital = 10000;
  const pnl = totalValue - initialCapital;
  const pnlPct = initialCapital > 0 ? (pnl / initialCapital) * 100 : 0;

  return (
    <div>
      <div className="card-title">P&L Dashboard</div>
      <div className="metric-grid">
        <div className="metric">
          <div className={`metric-value ${pnl >= 0 ? "text-green" : "text-red"}`}>
            ${pnl.toFixed(2)}
          </div>
          <div className="metric-label">Unrealized P&L</div>
        </div>
        <div className="metric">
          <div className={`metric-value ${pnlPct >= 0 ? "text-green" : "text-red"}`}>
            {pnlPct.toFixed(2)}%
          </div>
          <div className="metric-label">Return</div>
        </div>
      </div>
      <div style={{ marginTop: 8 }}>
        <div className="row-between">
          <span className="metric-label">Total Value</span>
          <span className="text-cyan" style={{ fontFamily: "'JetBrains Mono'", fontSize: "0.85rem" }}>
            ${totalValue.toFixed(2)}
          </span>
        </div>
      </div>
    </div>
  );
}

export default PnLDashboard;